# modules/pair_mapper.py

import json
import os
import pandas as pd
from datetime import datetime
from nubra_python_sdk.refdata.instruments import InstrumentData

def generate_pair_mapping(nubra, target_assets):
    """
    Fetches the latest instruments master and pairs the Spot (Cash)
    and current month Futures contract for the given target assets.
    Saves the output to config/instruments.json.
    """
    print("[MAPPER] Fetching instruments master DataFrame...")
    instruments = InstrumentData(nubra)
    
    # Load the full NSE dataframe natively via the SDK
    df = instruments.get_instruments_dataframe()
    
    mapping = {}
    
    # Get today's date as an integer (YYYYMMDD) to filter out expired contracts
    today_int = int(datetime.now().strftime('%Y%m%d'))
    
    for asset in target_assets:
        # 1. Find Spot (Cash) Instrument
        # The API docs note derivative_type could be 'STOCK' for cash equities.
        spot_df = df[(df['asset'] == asset) & (df['derivative_type'].isin(['STOCK', 'EQ']))]
        
        if spot_df.empty:
            print(f"[MAPPER] ⚠️ Warning: Spot not found for {asset}")
            continue
            
        spot_ref_id = int(spot_df.iloc[0]['ref_id'])
        
        # 2. Find Futures Instrument (Nearest Expiry)
        # Filters for FUT, FUTSTK, or FUTIDX
        fut_df = df[(df['asset'] == asset) & (df['derivative_type'].str.contains('FUT', na=False))]
        
        if fut_df.empty:
            print(f"[MAPPER] ⚠️ Warning: Futures not found for {asset}")
            continue
            
        # Filter for valid expiries and sort to get the nearest (Current Month)
        valid_futs = fut_df[fut_df['expiry'] >= today_int].sort_values(by='expiry')
        
        if valid_futs.empty:
            print(f"[MAPPER] ⚠️ Warning: No valid future expiries for {asset}")
            continue
            
        nearest_fut = valid_futs.iloc[0]
        fut_ref_id = int(nearest_fut['ref_id'])
        
        # 3. Store the required deterministic bounds data
        mapping[asset] = {
            "spot_ref_id": spot_ref_id,
            "futures_ref_id": fut_ref_id,
            "lot_size": int(nearest_fut['lot_size']),
            "tick_size": int(nearest_fut['tick_size']),
            "expiry": int(nearest_fut['expiry'])
        }
        print(f"[MAPPER]  Paired {asset}: Spot={spot_ref_id} | Fut={fut_ref_id} (Expiry: {nearest_fut['expiry']})")
        
    # Ensure config directory exists
    os.makedirs("config", exist_ok=True)
    
    # Save the mapping to disk for the ZeroMQ engines to consume
    with open("config/instruments.json", "w") as f:
        json.dump(mapping, f, indent=4)
        
    print("[MAPPER] Successfully saved pairs to config/instruments.json")
    return mapping