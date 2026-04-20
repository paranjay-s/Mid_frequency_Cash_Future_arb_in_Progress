# core_engines/2_math_engine.py

import os
import sys
import time
import json
import math
import zmq
import psutil
import traceback
from datetime import datetime
import numba as nb

# --- NUMBA C-COMPILED MATH CORE ---
@nb.njit() # Removed cache=True temporarily to prevent Windows permission errors
def calculate_arbitrage_state(
    s_bid, s_ask, f_bid, f_ask,
    current_ts, expiry_ts, ex_date_ts,
    r, D, condition, c_total
):
    """Executes C-speed deterministic bounds checking."""
    # 1. Continuous Time to Expiry (tau)
    tau = (expiry_ts - current_ts) / (365.0 * 24.0 * 60.0 * 60.0)
    if tau <= 0:
        return 0, 0.0, 0.0, 0.0, 0.0

    # Mid prices for theoretical gravity
    s_mid = (s_bid + s_ask) / 2.0
    
    # 2. Fair Value Routing
    if condition == 1 and ex_date_ts > current_ts:
        tau_d = (ex_date_ts - current_ts) / (365.0 * 24.0 * 60.0 * 60.0)
        pv_d = D * math.exp(-r * tau_d)
        f_fair = (s_mid - pv_d) * math.exp(r * tau)
    else:
        f_fair = s_mid * math.exp(r * tau)

    # 3. Dynamic Arbitrage Bounds
    b_star = f_fair - s_mid
    u_t = b_star + c_total
    l_t = b_star - c_total

    # 4. Actionable Spreads (Crossing the book)
    short_spread = f_bid - s_ask
    long_spread = f_ask - s_bid

    # 5. Deterministic Signal Generation
    signal = 0
    if short_spread > u_t:
        signal = -1  # Futures Overpriced -> Sell Fut, Buy Spot
    elif long_spread < l_t:
        signal = 1   # Futures Underpriced -> Buy Fut, Sell Spot
    elif (f_ask - s_bid <= b_star) or (f_bid - s_ask >= b_star):
        signal = 0   # Target Exit Condition Reached

    return signal, b_star, u_t, l_t, f_fair

def apply_core_affinity(core_id=1):
    try:
        p = psutil.Process(os.getpid())
        p.cpu_affinity([core_id])
        print(f"[MATH ENGINE] Process pinned strictly to CPU Core {core_id}.")
    except Exception as e:
        print(f"[MATH ENGINE] ⚠️ Could not set CPU affinity. Error: {e}")

def load_environment():
    with open("config/zmq_ports.json", "r") as f:
        ports = json.load(f)
    with open("config/instruments.json", "r") as f:
        instruments = json.load(f)
    with open("config/pre_market_params.json", "r") as f:
        params = json.load(f)

    ref_to_asset = {}
    ref_to_leg = {}
    for asset, data in instruments.items():
        ref_to_asset[str(data["spot_ref_id"])] = asset
        ref_to_leg[str(data["spot_ref_id"])] = "spot"
        
        ref_to_asset[str(data["futures_ref_id"])] = asset
        ref_to_leg[str(data["futures_ref_id"])] = "fut"
        
    return ports, instruments, params, ref_to_asset, ref_to_leg

def parse_date_to_ts(date_str, is_expiry=False):
    if not date_str:
        return 0.0
    try:
        if "-" in date_str: 
            dt = datetime.strptime(date_str, "%d-%b-%y")
        else: 
            dt = datetime.strptime(date_str, "%Y%m%d")
            
        if is_expiry:
            dt = dt.replace(hour=15, minute=30, second=0)
        return dt.timestamp()
    except Exception:
        return 0.0

def main():
    print("=== Booting Engine 2: Deterministic Math ===")
    apply_core_affinity(core_id=1)

    ports, instruments, params, ref_to_asset, ref_to_leg = load_environment()
    r = params["r"]

    context = zmq.Context()
    
    # Use 127.0.0.1 to force IPv4 on Windows
    sub_socket = context.socket(zmq.SUB)
    sub_socket.connect(f"tcp://127.0.0.1:{ports.get('L2_DATA', 5555)}")
    sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")
    
    draft_pub = context.socket(zmq.PUB)
    draft_pub.bind(f"tcp://127.0.0.1:{ports.get('DRAFT_SIGNALS', 5556)}")
    
    telemetry_pub = context.socket(zmq.PUB)
    telemetry_pub.connect(f"tcp://127.0.0.1:{ports.get('TELEMETRY', 5558)}")

    latest_ticks = {asset: {"spot": None, "fut": None} for asset in instruments.keys()}

    print("[MATH ENGINE] Numba JIT warming up. Listening for ticks on 127.0.0.1:5555...")

    while True:
        try:
            raw_msg = sub_socket.recv_string()
            ingest_ts = time.perf_counter_ns() 
            
            tick = json.loads(raw_msg)
            ref_id = str(tick["ref_id"])
            
            asset = ref_to_asset.get(ref_id)
            if not asset: continue
            leg = ref_to_leg[ref_id]

            latest_ticks[asset][leg] = tick
            
            spot_tick = latest_ticks[asset]["spot"]
            fut_tick = latest_ticks[asset]["fut"]
            
            if not spot_tick or not fut_tick:
                continue
                
            s_bid = spot_tick["bids"][0]["p"] / 100.0
            s_ask = spot_tick["asks"][0]["p"] / 100.0
            f_bid = fut_tick["bids"][0]["p"] / 100.0
            f_ask = fut_tick["asks"][0]["p"] / 100.0

            asset_params = params["assets"][asset]
            condition_int = 1 if asset_params["condition"] == "A" else 0
            
            expiry_str = str(instruments[asset]["expiry"]) # Force string for parser
            expiry_ts = parse_date_to_ts(expiry_str, is_expiry=True)
            ex_date_ts = parse_date_to_ts(asset_params["ex_date"])
            
            current_ts = tick["timestamp"] / 1_000_000_000.0 

            # Execute C-Compiled Math
            signal, b_star, u_t, l_t, f_fair = calculate_arbitrage_state(
                float(s_bid), float(s_ask), float(f_bid), float(f_ask),
                float(current_ts), float(expiry_ts), float(ex_date_ts),
                float(r), float(asset_params["D"]), int(condition_int), float(asset_params["C_total"])
            )

            calc_latency_ns = time.perf_counter_ns() - ingest_ts
            
            payload = {
                "asset": asset,
                "timestamp": tick["timestamp"],
                "signal": signal,
                "spread_short": f_bid - s_ask,
                "spread_long": f_ask - s_bid,
                "b_star": b_star,
                "u_t": u_t,
                "l_t": l_t,
                "f_fair": f_fair,
                "latency_ns": calc_latency_ns
            }

            if signal != 0:
                draft_pub.send_string(json.dumps(payload))
                
            # Telemetry fail-safed so it doesn't crash if your phone server isn't running
            try:
                telemetry_pub.send_string(json.dumps({"engine": "ENGINE_2", **payload}), zmq.NOBLOCK)
            except zmq.error.Again:
                pass

        except Exception as e:
            # THIS IS THE MAGIC LINE: It will now print the exact error to your terminal!
            print("\n❌ [CRASH DETECTED IN MATH LOOP]")
            traceback.print_exc()
            print("-" * 40)

if __name__ == "__main__":
    main()