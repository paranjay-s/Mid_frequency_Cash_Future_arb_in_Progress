# Mid-Frequency Cash-Futures Arbitrage (In Progress)

> **Status:** Currently working on it.
> **Current median Latency:** 0.25 ms

## Current System Architecture

```text



📦 MFT_CashFutures_Arbitrage
├── 📁 config
│✅ ├── 📄 instruments.json             # Static Spot-to-Futures mapping
│✅ ├── 📄 pre_market_params.json       
│✅ └── 📄 zmq_ports.json               # ZeroMQ topology (e.g., L2_DATA: 5555)
│
├── 📁 core_engines                     # THE 5 CONCURRENT OS PROCESSES (Subprocesses)
│✅ ├── 📄 1_data_ingestion.py          # WebSocket -> ZeroMQ PUB (Streams L2)
│✅ ├── 📄 2_math_engine.py             # SUB -> Numba Math -> PUB (Fires Draft Signals)
│   ├── 📄 3_ml_risk_engine.py          # SUB -> Feature Eng -> ONNX Veto -> Size -> PUB
│   ├── 📄 4_execution_engine.py        # SUB -> Executes via Nubra API  (to be updated with new ml verifying)
│✅ └── 📄 5_historical_logger.py       # SUB -> Batches L2 Data -> Async writes to Parquet/DB
│
├── 📁 modules                          # PURE LOGIC IMPORTS (No while-loops here)
│✅ ├── 📄 auth.py                      # Nubra SDK Auth
│✅ ├── 📄 pair_mapper.py               # Ticker selection
│✅ ├── 📄 inventory_tracker.py         # Tracks Cash/Futures exposure
│✅ ├── 📄 cloud_telemetry.py           # Pushes live anti broker data to Redis local on mobile
│   ├── 📄 feature_engineering.py       # (NEW) Stateless calculation of α, Entropy H, etc.
│   ├── 📄 signal_verifier.py           # (NEW) Part A: Evaluates C1-C5 ONNX logic
│✅ ├── 📄 pre_market.py                # (NEW) Costs calculator, WEBSCRAPPING-investing.com, NSE corporate actions
│✅ ├── 📄 data_sync_daemon.py          # pushing the historical data to google drive automatically
│   └── 📄 position_sizer.py            # (NEW) Part B: Kelly / Portfolio Optimization math
│
├── 📁 risk_models                      # ML ARTIFACTS
│✅ └── 📄 gatekeeper_int8.onnx and .pkl files   # Frozen INT8 quantized weights for sub-ms CPU inference
│
├── 📁 data_lake                        # (NEW) LOCAL STORAGE
│✅ └── 📄 raw_l2_archive.parquet       # High-VVV data saved for weekly cloud retraining, automatically pushed to google drive by data_sync_daemon.py in modules folder 
│
├── 📁 web_dashboard                     # NEW: Decoupled Web UI
│   ├── 📁 backend                       # PART A: FastAPI Server
│✅ │   └── 📄 api_server.py
│   └── 📁 frontend                      # PART B: React.js Application (half done)
│
└── 📄 main.py                          # The Master Script: boots the 5 core engines safely.


☁️ MFT_Cloud_Research Pipeline ✅ 




☁️ MFT_Cloud_Research
├── 📁 data_lake_archive               # Synced daily from your laptop
│   ├── 📁 2026-04-20
│   └── 📁 2026-04-21
│
├── 📁 mlflow_registry                 # MLflow SQLite DB and model artifacts
│
├── 📁 production_models               # The Bridge folder
│   ├── 📄 gatekeeper_latest.onnx      # The compiled ML model
│   └── 📄 feature_scalers.json        # MinMax/Standard scalers for live inputs
│
└── 📁 research_notebooks              # The automated Colab pipeline
    ├── 📄 01_Data_Alignment.ipynb     # Merges L2, Math, and Exec logs; runs Proxies
    ├── 📄 02_Feature_Engineering.ipynb# Generates X features and 21 Y targets
    ├── 📄 03_Model_Training.ipynb     # Hyperparameter tuning, MLflow logging
    └── 📄 04_Alpha_Tracking.ipynb     # Evaluates IC decay and backtest performance
