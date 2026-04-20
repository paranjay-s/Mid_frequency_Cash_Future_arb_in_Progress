# core_engines/5_historical_logger.py

import os
import time
import json
import zmq
import psutil
import threading
import pandas as pd
from datetime import datetime

# --- CONFIGURATION ---
FLUSH_INTERVAL_SEC = 120 # Flush RAM to HDD every 60 seconds
DATA_LAKE_DIR = "data_lake"

class HistoricalLogger:
    def __init__(self, zmq_port):
        self.zmq_port = zmq_port
        self.buffer = []
        self.lock = threading.Lock()
        
        # Pin to the last available CPU core
        self._apply_core_affinity()
        
        # Setup ZeroMQ
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.connect(f"tcp://127.0.0.1:{self.zmq_port}")
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")

    def _apply_core_affinity(self):
        """Pins the logger to the absolute last CPU core to isolate HDD latency."""
        try:
            total_cores = psutil.cpu_count(logical=True)
            last_core = total_cores - 1
            p = psutil.Process(os.getpid())
            p.cpu_affinity([last_core])
            print(f"[LOGGER] Process pinned strictly to CPU Core {last_core} (Last Core).")
        except Exception as e:
            print(f"[LOGGER] ⚠️ Could not set CPU affinity. Error: {e}")

    def _flatten_tick(self, tick):
        """Flattens nested L2 JSON into exactly 125 columns for ML Inference."""
        flat = {
            "ref_id": tick.get("ref_id"),
            "timestamp": tick.get("timestamp"),
            "ltp": tick.get("last_traded_price", 0),
            "ltq": tick.get("last_traded_quantity", 0),
            "volume": tick.get("volume", 0)
        }
        
        bids = tick.get("bids", [])
        asks = tick.get("asks", [])
        
        # Extract up to 20 levels. Pad with 0s if the book is thin.
        for i in range(20):
            # Bids
            if i < len(bids):
                flat[f"bid_p_{i+1}"] = bids[i]["p"]
                flat[f"bid_q_{i+1}"] = bids[i]["q"]
                flat[f"bid_n_{i+1}"] = bids[i]["n"]
            else:
                flat[f"bid_p_{i+1}"] = 0.0
                flat[f"bid_q_{i+1}"] = 0
                flat[f"bid_n_{i+1}"] = 0
                
            # Asks
            if i < len(asks):
                flat[f"ask_p_{i+1}"] = asks[i]["p"]
                flat[f"ask_q_{i+1}"] = asks[i]["q"]
                flat[f"ask_n_{i+1}"] = asks[i]["n"]
            else:
                flat[f"ask_p_{i+1}"] = 0.0
                flat[f"ask_q_{i+1}"] = 0
                flat[f"ask_n_{i+1}"] = 0
                
        return flat

    def _flush_loop(self):
        """Background thread: Wakes up every 60s, writes Parquet chunks to HDD, clears RAM."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        while True:
            time.sleep(FLUSH_INTERVAL_SEC)
            
            with self.lock:
                if not self.buffer:
                    continue
                # Make a shallow copy and instantly clear the RAM buffer to catch new ticks
                data_to_save = self.buffer.copy()
                self.buffer.clear()
            
            try:
                # Convert to DataFrame (125 Columns)
                df = pd.DataFrame(data_to_save)
                
                # Group by ref_id to save separate partitioned files
                for ref_id, group_df in df.groupby("ref_id"):
                    # Folder structure: data_lake/2026-03-24/1170913/
                    save_dir = os.path.join(DATA_LAKE_DIR, today_str, str(ref_id))
                    os.makedirs(save_dir, exist_ok=True)
                    
                    # File: chunk_1711234567.parquet
                    file_name = f"chunk_{int(time.time())}.parquet"
                    file_path = os.path.join(save_dir, file_name)
                    
                    # Write highly compressed Parquet to HDD
                    group_df.to_parquet(file_path, engine="pyarrow", compression="snappy")
                
                print(f"[LOGGER] Flushed {len(data_to_save)} ticks to HDD Data Lake.")
                
            except Exception as e:
                print(f"[LOGGER] ⚠️ HDD Write Error: {e}")

    def start(self):
        print(f"[LOGGER] Listening for L2 Data on port {self.zmq_port}...")
        
        # Start the async HDD flush thread
        threading.Thread(target=self._flush_loop, daemon=True).start()
        
        # Main loop: Catch ticks at maximum speed
        while True:
            try:
                raw_msg = self.socket.recv_string()
                tick = json.loads(raw_msg)
                
                flat_data = self._flatten_tick(tick)
                
                with self.lock:
                    self.buffer.append(flat_data)
                    
            except Exception as e:
                pass # Silent fail to maintain speed

if __name__ == "__main__":
    print("=== Booting Engine 5: Historical Data Logger ===")
    
    # Load ZeroMQ Ports
    try:
        with open("config/zmq_ports.json", "r") as f:
            ports = json.load(f)
        zmq_port = ports.get("L2_DATA", 5555)
    except FileNotFoundError:
        print("[LOGGER] CRITICAL: config/zmq_ports.json not found.")
        sys.exit(1)
        
    logger = HistoricalLogger(zmq_port)
    logger.start()