# core_engines/4_execution_engine.py

import os
import sys
import time
import json
import zmq
import psutil
import threading
from nubra_python_sdk.start_sdk import NubraEnv
from nubra_python_sdk.trading.trading_data import NubraTrader
from nubra_python_sdk.ticker import orderupdate
from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.auth import authenticate_nubra

# --- CRITICAL TOGGLE ---
PAPER_TRADE_MODE = True  # Set to False ONLY when ready to fire real capital

class ExecutionEngine:
    def __init__(self):
        print("=== Booting Engine 4: Execution & Liquidity Router ===")
        self._apply_core_affinity(core_id=2) # Shares core with Risk Engine

        self.ports, self.instruments = self.load_configs()
        
        # Local Inventory & Order Book Cache
        self.inventory = {asset: {"spot": 0, "fut": 0} for asset in self.instruments.keys()}
        self.l2_cache = {asset: {"spot": None, "fut": None} for asset in self.instruments.keys()}
        self.cache_lock = threading.Lock()

        # Auth & Trader Setup (Uses PROD auth safely. Multi_order only fires if PAPER=False)
        print("[EXECUTION] Authenticating with Broker...")

        self.nubra = authenticate_nubra(NubraEnv.PROD)
        self.trader = NubraTrader(self.nubra, version="V2")

        # ZeroMQ Setup
        self.context = zmq.Context()
        
        # 1. Listen to L2 Data for Order Book Sweeping (Port 5555)
        self.l2_sub = self.context.socket(zmq.SUB)
        self.l2_sub.connect(f"tcp://127.0.0.1:{self.ports.get('L2_DATA', 5555)}")
        self.l2_sub.setsockopt_string(zmq.SUBSCRIBE, "")
        
        # 2. Listen to Signals (Currently Math Engine 5556, later ML Engine)
        self.signal_sub = self.context.socket(zmq.SUB)
        self.signal_sub.connect(f"tcp://127.0.0.1:{self.ports.get('DRAFT_SIGNALS', 5556)}")
        self.signal_sub.setsockopt_string(zmq.SUBSCRIBE, "")
        
        # 3. Publish to Telemetry (Port 5558)
        self.telemetry_pub = self.context.socket(zmq.PUB)
        self.telemetry_pub.connect(f"tcp://127.0.0.1:{self.ports.get('TELEMETRY', 5558)}")

        # Start Background Threads
        threading.Thread(target=self._l2_cache_updater, daemon=True).start()
        
        if not PAPER_TRADE_MODE:
            threading.Thread(target=self._start_reconciliation_stream, daemon=True).start()

    def _apply_core_affinity(self, core_id):
        try:
            p = psutil.Process(os.getpid())
            p.cpu_affinity([core_id])
            print(f"[EXECUTION] Process pinned to CPU Core {core_id}.")
        except:
            pass

    def load_configs(self):
        with open("config/zmq_ports.json", "r") as f:
            ports = json.load(f)
        with open("config/instruments.json", "r") as f:
            instruments = json.load(f)
        return ports, instruments

    def _l2_cache_updater(self):
        """Silently maintains the latest 20-level depth for liquidity routing."""
        # Reverse map for quick lookups
        ref_map = {}
        for asset, data in self.instruments.items():
            ref_map[str(data["spot_ref_id"])] = (asset, "spot")
            ref_map[str(data["futures_ref_id"])] = (asset, "fut")

        while True:
            try:
                msg = json.loads(self.l2_sub.recv_string())
                ref_id = str(msg["ref_id"])
                if ref_id in ref_map:
                    asset, leg = ref_map[ref_id]
                    with self.cache_lock:
                        self.l2_cache[asset][leg] = msg
            except:
                pass

    def calculate_sweep_price(self, book_side, target_qty, is_buy):
        """
        Calculates the exact Limit Price needed to fill the target quantity
        by walking down the Level 2 order book.
        """
        accumulated_qty = 0
        worst_price_hit = 0.0

        for level in book_side:
            # Convert paise back to rupees for calculation if ingestion didn't
            price = level["p"] / 100.0 if level["p"] > 10000 else level["p"] 
            qty = level["q"]
            
            accumulated_qty += qty
            worst_price_hit = price
            
            if accumulated_qty >= target_qty:
                break
                
        # Safety margin: If the book is too thin, we just return the deepest level we found.
        # In a full Risk Engine setup, we would abort the trade here if accumulated_qty < target_qty.
        return worst_price_hit

    def execute_arbitrage(self, asset, signal):
        """Builds the multi-leg payload and fires it."""
        # 1. Get Target Quantity (Hardcoded to 1 lot for now, ML Risk Engine will dictate this later)
        qty = self.instruments[asset].get("lot_size", 175)
        
        with self.cache_lock:
            spot_book = self.l2_cache[asset]["spot"]
            fut_book = self.l2_cache[asset]["fut"]
            
        if not spot_book or not fut_book:
            print(f"⚠️ [EXECUTION] Cannot execute {asset}. Missing L2 Cache.")
            return

        # 2. Liquidity Routing (Calculate Marketable Limit Prices)
        if signal == -1: # Short Basis: Sell Fut, Buy Spot
            spot_price = self.calculate_sweep_price(spot_book["asks"], qty, is_buy=True)
            fut_price = self.calculate_sweep_price(fut_book["bids"], qty, is_buy=False)
            spot_side = "ORDER_SIDE_BUY"
            fut_side = "ORDER_SIDE_SELL"
            
        elif signal == 1: # Long Basis: Buy Fut, Sell Spot
            spot_price = self.calculate_sweep_price(spot_book["bids"], qty, is_buy=False)
            fut_price = self.calculate_sweep_price(fut_book["asks"], qty, is_buy=True)
            spot_side = "ORDER_SIDE_SELL"
            fut_side = "ORDER_SIDE_BUY"
        else:
            return

        # print(f"\n⚡ [ROUTING] {asset} | QTY: {qty} | SPOT LMT: ₹{spot_price:.2f} | FUT LMT: ₹{fut_price:.2f}")

        if PAPER_TRADE_MODE:
            self._simulate_execution(asset, signal, qty, spot_price, fut_price)
        else:
            self._live_execution(asset, qty, spot_price, fut_price, spot_side, fut_side)

    def _simulate_execution(self, asset, signal, qty, spot_price, fut_price):
        """Paper Trading logic."""
        # Update Simulated Inventory
        if signal == -1:
            self.inventory[asset]["spot"] += qty
            self.inventory[asset]["fut"] -= qty
        elif signal == 1:
            self.inventory[asset]["spot"] -= qty
            self.inventory[asset]["fut"] += qty

        # Push to Telemetry
        payload = {
            "engine": "ENGINE_4",
            "status": "PAPER_FILL",
            "asset": asset,
            "signal": signal,
            "qty": qty,
            "avg_spot_price": spot_price,
            "avg_fut_price": fut_price,
            "inventory": self.inventory[asset]
        }
        self.telemetry_pub.send_string(json.dumps(payload))
        # print(f"✅ [PAPER FILL] Simulated successful. Inventory: {self.inventory[asset]}")

    def _live_execution(self, asset, qty, spot_price, fut_price, spot_side, fut_side):
        """Fires the Nubra multi_order API using exchange-native integers (Paise)."""
        spot_ref = self.instruments[asset]["spot_ref_id"]
        fut_ref = self.instruments[asset]["futures_ref_id"]
        
        payload = [
            {
                "ref_id": int(spot_ref),
                "order_type": "ORDER_TYPE_REGULAR",
                "order_qty": int(qty),
                "order_side": spot_side,
                "order_delivery_type": "ORDER_DELIVERY_TYPE_IDAY",
                "validity_type": "DAY", # Use DAY to ensure fill, IOC for aggressive sweep
                "price_type": "LIMIT",
                "order_price": int(spot_price * 100), # Convert to Paise
                "exchange": "NSE",
                "tag": f"ARB_SPOT_{asset}"
            },
            {
                "ref_id": int(fut_ref),
                "order_type": "ORDER_TYPE_REGULAR",
                "order_qty": int(qty),
                "order_side": fut_side,
                "order_delivery_type": "ORDER_DELIVERY_TYPE_IDAY",
                "validity_type": "DAY",
                "price_type": "LIMIT",
                "order_price": int(fut_price * 100), # Convert to Paise
                "exchange": "NSE",
                "tag": f"ARB_FUT_{asset}"
            }
        ]
        
        try:
            result = self.trader.multi_order(payload)
            print(f"🚀 [LIVE EXECUTION] Sent to Exchange. Order IDs: {[o.order_id for o in result.orders]}")
            # Note: The WebSocket thread will catch the fill and update inventory automatically.
        except Exception as e:
            print(f"❌ [API REJECTED] Failed to place live multi-order: {e}")

    def _start_reconciliation_stream(self):
        """Background WebSocket to catch live Fill updates from the Exchange."""
        def on_trade_update(msg):
            print(f"✅ [BROKER FILL] {msg.response_type} | Qty: {msg.order_params.filled_qty} @ ₹{msg.order_params.avg_fill_price / 100.0}")
            # In production, parse msg.order_params.ref_id, update self.inventory, and send to Telemetry here.
            
        def on_error(err): pass
        def on_close(reason): pass
        def on_connect(msg): print(f"[RECONCILIATION] WebSocket Live: {msg}")

        socket = orderupdate.OrderUpdate(
            client=self.nubra,
            on_trade_update=on_trade_update,
            on_order_update=lambda msg: None, # Ignore non-fill events for now
            on_connect=on_connect,
            on_close=on_close,
            on_error=on_error,
        )
        socket.connect("V2")
        socket.keep_running()

    def start(self):
        print(f"[EXECUTION] Waiting for Math/Risk Signals on port {self.ports.get('DRAFT_SIGNALS', 5556)}...")
        while True:
            try:
                # Poller logic: Wait for a signal to arrive
                msg = self.signal_sub.recv_string()
                data = json.loads(msg)
                
                asset = data.get("asset")
                signal = data.get("signal")
                
                if signal != 0:
                    self.execute_arbitrage(asset, signal)
                    
            except Exception as e:
                pass

if __name__ == "__main__":
    engine = ExecutionEngine()
    engine.start()