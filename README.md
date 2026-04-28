# Mid_frequency_Cash_Future_arb_in_Progress

Currently working on it 

Current median Latency = 0.25 ms 

📦 MFT_CashFutures_Arbitrage
├── 📁 config
│   ├── 📄 instruments.json
│   ├── 📄 pre_market_params.json       
│   └── 📄 zmq_ports.json
│
├── 📁 core_engines                     
│   ├── 📄 1_data_ingestion.py          # L2 WebSocket -> ZeroMQ (5555)
│   ├── 📄 2_math_engine.py             # Math Bounds -> ZeroMQ (5556)
│   ├── 📄 3_ml_risk_engine.py          # NEW: Loads ONNX -> Generates C1-C5 -> Verified Signal
│   ├── 📄 4_execution_engine.py        # Listens to Verified Signals -> Nubra API -> ZeroMQ (5557)
│   └── 📄 5_historical_logger.py       # ZMQ Poller -> Parquet Data Lake
│
├── 📁 modules                          
│   ├── 📄 auth.py                      
│   ├── 📄 pair_mapper.py               
│   ├── 📄 inventory_tracker.py         
│   ├── 📄 cloud_telemetry.py           # Pushes UI data to Redis
│   ├── 📄 model_updater.py             # NEW: The Bridge. Pulls new ONNX from Google Drive
│   ├── 📄 feature_engineering.py       # NEW: Live, stateless calc of α, Entropy H, VPIN
│   ├── 📄 signal_verifier.py           # NEW: Evaluates the Phi >= 0.70 equation
│   ├── 📄 pre_market.py                
│   └── 📄 data_sync_daemon.py          # NEW: Uploads Parquet files to Drive at 4:00 PM
│
├── 📁 risk_models                      # Local sync target for the Bridge
│   ├── 📄 gatekeeper_latest.onnx       
│   └── 📄 feature_scalers.json         
│
├── 📁 data_lake                        # Local raw storage
│   ├── 📁 2026-04-22
│   │   ├── 📁 1170913                  # L2 Data
│   │   ├── 📁 MATH_LOGS                
│   │   └── 📁 EXECUTION_LOGS           
│
├── 📁 web_dashboard                    # Tailscale Web UI
│   ├── 📁 backend                      # FastAPI
│   └── 📁 frontend                     # React + Tailwind
│
└── 📄 main.py                          # Boots the 5 engines, web backend, and telemetry


Offline ML workflow
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
    └── 📄 04_Alpha_Tracking.ipynb     # Evaluates IC decay and backtest performance☁️ MFT_Cloud_Research
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
    