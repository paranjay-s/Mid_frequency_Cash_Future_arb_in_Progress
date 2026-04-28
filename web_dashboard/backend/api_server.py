# web_dashboard/backend/api_server.py

import json
import zlib
import time
import logging
import threading
import redis
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import sys

# Configure professional logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger("API_SERVER")

# Tailscale Phone IP Configuration
PHONE_IP = "100.125.184.39"  # UPDATE THIS TO YOUR PHONE'S TAILSCALE IP
REDIS_PORT = 6379

app = FastAPI(title="MFT Command Center API", version="1.0.0")

# Enable CORS for React Frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to specific IPs in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global RAM Buffer
class State:
    math_data = []
    trade_logs = []
    instruments = []

try:
    db = redis.Redis(host=PHONE_IP, port=REDIS_PORT, db=0, socket_timeout=2)
    db.ping()
    logger.info(f"Connected to Redis via Tailscale at {PHONE_IP}")
except Exception as e:
    logger.error(f"Redis connection failed: {e}")

def load_dynamic_instruments():
    """Reads target assets directly from the config file."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config", "instruments.json")
    try:
        with open(config_path, "r") as f:
            data = json.load(f)
            State.instruments = list(data.keys())
            logger.info(f"Loaded instruments: {State.instruments}")
    except Exception as e:
        logger.error(f"Failed to load instruments config: {e}")

def background_redis_worker():
    """Asynchronous polling of Redis queue."""
    while True:
        try:
            compressed_data = db.lpop('mft_logs')
            if compressed_data:
                json_str = zlib.decompress(compressed_data).decode('utf-8')
                events = json.loads(json_str)
                
                for event in events:
                    if event.get("engine") == "ENGINE_2":
                        State.math_data.append(event)
                    elif event.get("engine") == "ENGINE_4":
                        State.trade_logs.append(event)
                
                # Truncate to prevent memory overflow
                State.math_data = State.math_data[-1000:]
                State.trade_logs = State.trade_logs[-100:]
            else:
                time.sleep(0.05)
        except Exception:
            time.sleep(0.1)

# Initialize background tasks on startup
@app.on_event("startup")
def startup_event():
    load_dynamic_instruments()
    threading.Thread(target=background_redis_worker, daemon=True).start()

# --- API ENDPOINTS ---

@app.get("/api/health")
def health_check():
    return {"status": "online", "timestamp": time.time()}

@app.get("/api/config")
def get_config():
    return {"assets": State.instruments}

@app.get("/api/metrics")
def get_metrics():
    kill_status = db.get("SYSTEM_KILL_SWITCH")
    is_killed = True if kill_status and kill_status.decode() == "1" else False
    
    return {
        "is_killed": is_killed,
        "math_data": State.math_data,
        "trade_logs": State.trade_logs
    }

@app.post("/api/kill")
def trigger_kill_switch():
    try:
        db.set("SYSTEM_KILL_SWITCH", "1")
        logger.warning("KILL SWITCH ACTIVATED VIA API.")
        return {"status": "KILLED", "timestamp": time.time()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))