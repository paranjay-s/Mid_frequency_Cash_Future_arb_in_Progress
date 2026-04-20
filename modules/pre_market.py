# modules/pre_market.py

# modules/pre_market.py

import os
import json
import math
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
import io
from nubra_python_sdk.marketdata.market_data import MarketData

# --- CONFIGURATION ---
DEFAULT_YIELD = 6.85 
BROKERAGE_PLAN = "B" # Switch to "B" when your account gets upgraded
SAFETY_BUFFER = 0.20 # ₹0.50 per share to absorb intraday tax drift & slippage

def fetch_risk_free_rate():
    print("[PRE-MARKET] Fetching 90-day T-Bill Yield from Investing.com...")
    url = "https://in.investing.com/rates-bonds/india-3-month-bond-yield"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        yield_element = soup.find(attrs={"data-test": "instrument-price-last"})
        if yield_element:
            yield_val = float(yield_element.text.strip())
            print(f"[PRE-MARKET] Successfully scraped Yield: {yield_val}%")
        else:
            raise ValueError("Could not find yield element.")
    except Exception as e:
        print(f"[PRE-MARKET] ⚠️ Scrape failed ({e}). Using default yield: {DEFAULT_YIELD}%")
        yield_val = DEFAULT_YIELD

    continuous_r = math.log(1 + (yield_val / 100))
    print(f"[PRE-MARKET] Continuous Risk-Free Rate (r): {continuous_r:.6f}")
    return continuous_r

def fetch_corporate_actions(target_assets):
    print("[PRE-MARKET] Checking NSE Corporate Actions for Dividends...")
    url = "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
    
    # Upgraded headers to bypass NSE bot protection
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    
    dividends = {asset: {"D": 0.0, "ex_date": None, "condition": "B"} for asset in target_assets}
    
    try:
        session = requests.Session()
        # Ping the homepage first to establish valid cookies
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        
        # Now hit the API
        response = session.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            for item in data:
                symbol = item.get("symbol")
                if symbol in target_assets:
                    purpose = item.get("purpose", "").lower()
                    if "dividend" in purpose and "rs" in purpose:
                        try:
                            words = purpose.replace("-", " ").split()
                            rs_index = words.index("rs")
                            div_value = float(words[rs_index + 1])
                            ex_date_str = item.get("exDate")
                            
                            dividends[symbol] = {"D": div_value, "ex_date": ex_date_str, "condition": "A"}
                            print(f"[PRE-MARKET] 💰 Found Dividend for {symbol}: ₹{div_value}")
                        except Exception:
                            pass
        else:
            print(f"[PRE-MARKET] ⚠️ NSE returned status {response.status_code}. Defaulting to Condition B.")
            
    except Exception as e:
        print(f"[PRE-MARKET] ⚠️ NSE API Scrape failed ({e}). Defaulting to Condition B.")
        
    return dividends

def calculate_per_share_cost(spot_price, fut_price, lot_size, plan="B"):
    spot_turnover = spot_price * 2 
    fut_turnover = fut_price * 2   
    
    if plan == "A":
        brok_spot = spot_turnover * 0.0003 
        brok_fut = 20.0 / lot_size 
        brokerage_per_share = brok_spot + brok_fut
    else:
        brokerage_per_share = 80.0 / lot_size

    exchange_spot = spot_turnover * 0.0000322 
    exchange_fut = fut_turnover * 0.0000173
    total_exchange = exchange_spot + exchange_fut
    
    stt_spot = spot_price * 0.00025 
    stt_fut = fut_price * 0.00020   
    total_stt = stt_spot + stt_fut
    
    sebi_total = (spot_turnover + fut_turnover) * 0.000001
    
    stamp_spot = spot_price * 0.00003 
    stamp_fut = fut_price * 0.00002   
    total_stamp = stamp_spot + stamp_fut
    
    gst = (brokerage_per_share + total_exchange + sebi_total) * 0.18
    
    raw_c_total = brokerage_per_share + total_exchange + total_stt + sebi_total + total_stamp + gst
    return raw_c_total + SAFETY_BUFFER

def generate_pre_market_params(nubra_client):
    """Reads instruments, fetches real prices, calculates exact limits, saves params."""
    print("\n=== Running Pre-Market Setup ===")
    
    try:
        with open("config/instruments.json", "r") as f:
            instruments = json.load(f)
    except FileNotFoundError:
        print("CRITICAL: config/instruments.json not found. Run mapper first.")
        return
        
    target_assets = list(instruments.keys())
    
    r = fetch_risk_free_rate()
    corp_actions = fetch_corporate_actions(target_assets)
    
    # Initialize Market Data API
    market_data = MarketData(nubra_client)
    
    pre_market_data = {
        "timestamp": datetime.now().isoformat(),
        "r": r,
        "assets": {}
    }
    
    for asset in target_assets:
        lot_size = instruments[asset].get("lot_size", 500)
        
        # Fetch Real Price Dynamically!
        try:
            price_resp = market_data.current_price(asset)
            # Nubra returns paise. Convert to Rupees. 
            # Use price if prev_close is 0 or missing.
            raw_paise = price_resp.prev_close if price_resp.prev_close else price_resp.price
            real_price = raw_paise / 100.0
        except Exception as e:
            print(f"[PRE-MARKET] ⚠️ Failed to fetch price for {asset} ({e}). Using 1500.0 fallback.")
            real_price = 1500.0
        
        # We pass real_price to both spot and fut because basis spread doesn't materially alter tax percentages
        c_total = calculate_per_share_cost(real_price, real_price, lot_size, plan=BROKERAGE_PLAN)
        
        pre_market_data["assets"][asset] = {
            "D": corp_actions[asset]["D"],
            "ex_date": corp_actions[asset]["ex_date"],
            "condition": corp_actions[asset]["condition"],
            "C_total": round(c_total, 4)
        }
        print(f"[PRE-MARKET] {asset} @ ₹{real_price} -> Lot: {lot_size} | C_total: ₹{c_total:.4f}/share (Includes ₹{SAFETY_BUFFER} Buffer)")

    os.makedirs("config", exist_ok=True)
    with open("config/pre_market_params.json", "w") as f:
        json.dump(pre_market_data, f, indent=4)
        
    print("[PRE-MARKET] ✅ pre_market_params.json successfully generated.")