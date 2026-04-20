# main.py
# main.py

import json
import sys
import time
import subprocess
from datetime import datetime
from nubra_python_sdk.start_sdk import NubraEnv
from modules.auth import authenticate_nubra
from modules.pair_mapper import generate_pair_mapping
from modules.pre_market import generate_pre_market_params 

TARGET_ASSETS = ["HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "TCS"]
NSE_HOLIDAYS_2026 = ["2026-01-26", "2026-03-03"]

def load_config():
    try:
        with open("config/zmq_ports.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("CRITICAL: config/zmq_ports.json not found.")
        sys.exit(1)

def wait_for_market_prep():
    now = datetime.now()
    if now.weekday() >= 5 or now.strftime("%Y-%m-%d") in NSE_HOLIDAYS_2026:
        print("[CLOCK] Market is closed today. Exiting.")
        sys.exit(0)

    prep_time = now.replace(hour=9, minute=13, second=0, microsecond=0)
    if now > now.replace(hour=15, minute=30, second=0):
        print("[CLOCK] Market closed for today. Exiting.")
        sys.exit(0)

    if now < prep_time:
        time.sleep((prep_time - now).total_seconds())

def main():
    print("=== Booting MFT Cash-Futures Arbitrage System ===")
    ports = load_config()
    
    try:
        nubra = authenticate_nubra(NubraEnv.PROD) 
    except Exception as e:
        sys.exit(1)

    wait_for_market_prep()
    
    generate_pair_mapping(nubra, TARGET_ASSETS)
    generate_pre_market_params(nubra)

    processes = []
    try:
        print("[SYSTEM] Booting Core Engines & Telemetry...")
        
        # 0. Boot Telemetry
        p_telemetry = subprocess.Popen([sys.executable, "modules/cloud_telemetry.py"])
        processes.append(p_telemetry)
        time.sleep(4)
        
        # 1. Boot Ingestion (Wait 3 seconds for it to establish WebSocket)
        p1 = subprocess.Popen([sys.executable, "core_engines/1_data_ingestion.py"])
        processes.append(p1)
        time.sleep(4)  # <--- CRITICAL FIX 
        
        # 2. Boot Math Engine (Wait 1 second)
        p2 = subprocess.Popen([sys.executable, "core_engines/2_math_engine.py"])
        processes.append(p2)
        time.sleep(4)

        # 3. Boot Execution Engine (Safe to auth now)
        p4 = subprocess.Popen([sys.executable, "core_engines/4_execution_engine.py"])
        processes.append(p4)
        time.sleep(4)

        # 4. Boot Logger
        p5 = subprocess.Popen([sys.executable, "core_engines/5_historical_logger.py"])
        processes.append(p5)
        time.sleep(2)
        
        print("[SYSTEM] ALL ENGINES ONLINE. Press Ctrl+C to shut down.")
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[SYSTEM] Terminating engines...")
        for p in processes:
            p.terminate()
            p.wait() 
        print("[SYSTEM] System stopped cleanly.")

if __name__ == "__main__":
    main()