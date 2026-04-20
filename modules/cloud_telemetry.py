# modules/cloud_telemetry.py

import zmq
import json
import time
import zlib
import threading
import redis
import os

# ---> UPDATE THIS WITH THE NEW IP YOU JUST FOUND <---
PHONE_USB_IP = "192.168.1.9"  
REDIS_PORT = 6379

class TelemetryBuffer:
    def __init__(self, ports_config):
        self.zmq_port = ports_config.get("TELEMETRY", 5558)
        self.buffer = []
        self.lock = threading.Lock()
        
        print(f"[TELEMETRY] Connecting to Phone Database at {PHONE_USB_IP}:{REDIS_PORT}...")
        try:
            self.db = redis.Redis(host=PHONE_USB_IP, port=REDIS_PORT, db=0, socket_timeout=2)
            self.db.ping() 
            print("[TELEMETRY] ✅ Connected to Android Server successfully.")
        except Exception as e:
            print(f"[TELEMETRY] ⚠️ CRITICAL: Could not connect. Error: {e}")

    def start_listening(self):
        threading.Thread(target=self._zmq_listener_loop, daemon=True).start()
        threading.Thread(target=self._flush_loop, daemon=True).start()

    def _zmq_listener_loop(self):
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        
        # --- THE CRITICAL FIX: TELEMETRY MUST BIND, NOT CONNECT ---
        socket.bind(f"tcp://127.0.0.1:{self.zmq_port}")
        socket.setsockopt_string(zmq.SUBSCRIBE, "") 

        print(f"[TELEMETRY] Listening for internal events on port {self.zmq_port}...")

        while True:
            try:
                message = socket.recv_string()
                event_data = json.loads(message)
                with self.lock:
                    self.buffer.append(event_data)
            except Exception as e:
                print(f"[TELEMETRY] Error reading ZeroMQ: {e}")

    def _flush_loop(self):
        while True:
            time.sleep(5.0) # The 1-second batching window
            
            with self.lock:
                if not self.buffer:
                    continue 
                batch_to_send = self.buffer.copy()
                self.buffer.clear()

            try:
                if hasattr(self, 'db'):
                    json_str = json.dumps(batch_to_send)
                    compressed_binary = zlib.compress(json_str.encode('utf-8'))
                    
                    self.db.rpush('mft_logs', compressed_binary)
                    # print(f"[TELEMETRY] Flushed {len(batch_to_send)} events to phone.")
                
            except Exception as e:
                # print(f"[TELEMETRY] ⚠️ Failed to push to phone: {e}")
                print("--")

if __name__ == "__main__":
    print("=== Booting Telemetry Bridge ===")
    
    try:
        with open("config/zmq_ports.json", "r") as f:
            ports = json.load(f)
    except FileNotFoundError:
        ports = {"TELEMETRY": 5558}

    telemetry = TelemetryBuffer(ports)
    telemetry.start_listening()
    
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        print("[TELEMETRY] Shutting down.")