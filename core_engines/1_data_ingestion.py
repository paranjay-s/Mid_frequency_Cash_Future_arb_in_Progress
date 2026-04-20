# core_engines/1_data_ingestion.py
# core_engines/1_data_ingestion.py

import os
import sys
import time
import json
import zmq
import psutil
from nubra_python_sdk.ticker import websocketdata
from nubra_python_sdk.start_sdk import NubraEnv

# Add the parent directory to sys.path so it can find the 'modules' folder
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.auth import authenticate_nubra

def apply_core_affinity(core_id=0):
    try:
        p = psutil.Process(os.getpid())
        p.cpu_affinity([core_id])
        print(f"[INGESTION] Process pinned strictly to CPU Core {core_id}.")
    except Exception as e:
        print(f"[INGESTION] ⚠️ Could not set CPU affinity. OS will manage cores. Error: {e}")

def load_configs():
    with open("config/zmq_ports.json", "r") as f:
        ports = json.load(f)
    with open("config/instruments.json", "r") as f:
        instruments = json.load(f)
    return ports, instruments

def main():
    print("=== Booting Engine 1: Data Ingestion (WebSocket -> ZeroMQ) ===")
    
    apply_core_affinity(core_id=0)

    ports, instruments = load_configs()
    zmq_port = ports.get("L2_DATA", 5555)

    ref_ids_to_subscribe = []
    for asset, data in instruments.items():
        ref_ids_to_subscribe.append(str(data["spot_ref_id"]))
        ref_ids_to_subscribe.append(str(data["futures_ref_id"]))

    print(f"[INGESTION] Target Ref IDs: {ref_ids_to_subscribe}")

    context = zmq.Context()
    zmq_socket = context.socket(zmq.PUB)
    zmq_socket.bind(f"tcp://*:{zmq_port}")
    print(f"[INGESTION] ZeroMQ PUB Pipe bound to port {zmq_port}.")

    print("[INGESTION] Authenticating SDK...")
    nubra = authenticate_nubra(NubraEnv.PROD)

    def on_orderbook_data(msg):
        try:
            bids = [{"p": b.price, "q": b.quantity, "n": b.num_orders} for b in msg.bids if b.price]
            asks = [{"p": a.price, "q": a.quantity, "n": a.num_orders} for a in msg.asks if a.price]

            if not bids or not asks:
                return

            # --- UPDATED PACKET ---
            # Now includes LTP, LTQ, and Volume for the Risk Engine
            packet = {
                "ref_id": msg.ref_id,
                "timestamp": msg.timestamp,
                "bids": bids,
                "asks": asks,
                "last_traded_price": msg.last_traded_price,
                "last_traded_quantity": msg.last_traded_quantity,
                "volume": msg.volume
            }
            
            zmq_socket.send_string(json.dumps(packet))

        except Exception:
            pass

    def on_connect(msg):
        print(f"[INGESTION WS] Connected: {msg}")

    def on_close(reason):
        print(f"[INGESTION WS] Closed: {reason}")

    def on_error(err):
        print(f"[INGESTION WS] Error: {err}")

    ws_client = websocketdata.NubraDataSocket(
        client=nubra,
        on_orderbook_data=on_orderbook_data,
        on_connect=on_connect,
        on_close=on_close,
        on_error=on_error,
    )

    ws_client.connect()
    ws_client.subscribe(ref_ids_to_subscribe, data_type="orderbook")
    
    print("[INGESTION] Stream is LIVE. Engine running natively.")
    
    # Blocks the thread, keeping the WebSocket alive natively
    ws_client.keep_running()

if __name__ == "__main__":
    main()