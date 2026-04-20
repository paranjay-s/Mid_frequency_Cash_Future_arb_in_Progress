# dashboard.py (RUN THIS ON YOUR LAPTOP)

from flask import Flask, jsonify, render_template_string
import redis
import zlib
import json
import threading
import time
from pyngrok import ngrok
import logging

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

# --- NGROK SETUP (Works perfectly on Windows/Mac) ---
NGROK_TOKEN = "39RRZC6Yk8swKVhLzfICd3HVWkj_4sAiWXJEAf914a2t1Y4Qn"
try:
    ngrok.set_auth_token(NGROK_TOKEN)
    public_url = ngrok.connect(5000).public_url
    print(f"\n====================================================")
    print(f"🌍 GLOBAL DASHBOARD LIVE AT: {public_url}")
    print(f"====================================================\n")
except Exception as e:
    print(f"Ngrok failed. Running locally only. Error: {e}")

# --- REDIS SETUP (Connects to Phone) ---
PHONE_IP = "192.168.1.9" # <--- UPDATE THIS TO YOUR PHONE'S IP
db = redis.Redis(host=PHONE_IP, port=6379, db=0)

# --- GLOBAL RAM BUFFER ---
LATEST_MATH = []
LATEST_TRADES = []

def background_redis_worker():
    global LATEST_MATH, LATEST_TRADES
    while True:
        try:
            compressed_data = db.lpop('mft_logs')
            if compressed_data:
                json_str = zlib.decompress(compressed_data).decode('utf-8')
                events = json.loads(json_str)
                
                for event in events:
                    if event.get("engine") == "ENGINE_2":
                        LATEST_MATH.append(event)
                    elif event.get("engine") == "ENGINE_4":
                        LATEST_TRADES.append(event)
                        
                LATEST_MATH = LATEST_MATH[-1000:] # Keep more data for history
                LATEST_TRADES = LATEST_TRADES[-50:]
            else:
                time.sleep(0.1)
        except Exception:
            time.sleep(0.1)

threading.Thread(target=background_redis_worker, daemon=True).start()

@app.route('/api/data')
def get_data():
    kill_status = db.get("SYSTEM_KILL_SWITCH")
    is_killed = True if kill_status and kill_status.decode() == "1" else False
    return jsonify({"math": LATEST_MATH, "trades": LATEST_TRADES, "is_killed": is_killed})

@app.route('/api/kill', methods=['POST'])
def kill_switch():
    db.set("SYSTEM_KILL_SWITCH", "1")
    return jsonify({"status": "KILLED"})

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8"> <title>MFT Global Command Center</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        body { background-color: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; margin: 0; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; padding-bottom: 15px; margin-bottom: 20px;}
        .btn-kill { background-color: #da3633; color: white; border: none; padding: 12px 24px; font-size: 16px; font-weight: bold; border-radius: 6px; cursor: pointer; transition: 0.2s;}
        .btn-kill:hover { background-color: #b62324; }
        .status-badge { padding: 8px 16px; border-radius: 20px; font-weight: bold; font-size: 14px; border: 1px solid;}
        .live { background-color: rgba(46, 160, 67, 0.15); color: #3fb950; border-color: #2ea043; }
        .dead { background-color: rgba(218, 54, 51, 0.15); color: #ff7b72; border-color: #da3633; }
        .controls { display: flex; gap: 15px; margin-bottom: 20px; align-items: center;}
        select { background-color: #21262d; color: #c9d1d9; border: 1px solid #30363d; padding: 10px; border-radius: 6px; font-size: 16px; outline: none;}
        .metrics-grid { display: flex; gap: 15px; margin-bottom: 20px; }
        .metric-card { background-color: #161b22; padding: 20px; border-radius: 8px; flex: 1; text-align: center; border: 1px solid #30363d;}
        .metric-title { font-size: 14px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px;}
        .metric-value { font-size: 28px; font-weight: bold; color: #58a6ff; margin-top: 8px;}
        #chart { width: 100%; height: 500px; background-color: #161b22; border-radius: 8px; border: 1px solid #30363d;}
        table { width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px; background-color: #161b22; border-radius: 8px; overflow: hidden;}
        th, td { text-align: left; padding: 12px 15px; border-bottom: 1px solid #30363d; }
        th { background-color: #21262d; color: #8b949e; font-weight: 600; }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1 style="margin: 0; color: #58a6ff;">⚡ MFT Global Command Center</h1>
            <p style="color: #8b949e; margin: 5px 0 0 0;">Arbitrage Engine Telemetry & Risk Bounds</p>
        </div>
        <div style="display: flex; gap: 20px; align-items: center;">
            <div id="sys-status" class="status-badge live">SYSTEM LIVE</div>
            <button class="btn-kill" onclick="triggerKillSwitch()">🚨 EMERGENCY STOP</button>
        </div>
    </div>

    <div class="controls">
        <strong style="color: #8b949e;">Select Asset to Monitor:</strong>
        <select id="asset-selector" onchange="forceUpdate()">
            <option value="ALL">All Assets (Aggregated)</option>
            <option value="TCS" selected>TCS</option>
            <option value="RELIANCE">RELIANCE</option>
            <option value="HDFCBANK">HDFCBANK</option>
            <option value="ICICIBANK">ICICIBANK</option>
            <option value="INFY">INFY</option>
        </select>
    </div>

    <div class="metrics-grid">
        <div class="metric-card"><div class="metric-title">Latest Signal</div><div id="m-signal" class="metric-value">--</div></div>
        <div class="metric-card"><div class="metric-title">Short Spread</div><div id="m-spread" class="metric-value">--</div></div>
        <div class="metric-card"><div class="metric-title">Transaction Cost Barrier (u_t)</div><div id="m-ut" class="metric-value">--</div></div>
        <div class="metric-card"><div class="metric-title">Math Latency</div><div id="m-latency" class="metric-value">--</div></div>
    </div>

    <div id="chart"></div>

    <h3 style="margin-top: 30px; color: #58a6ff;">📝 Execution Logs</h3>
    <table>
        <thead><tr><th>Asset</th><th>Status</th><th>Signal</th><th>Qty</th><th>Spot Px</th><th>Fut Px</th></tr></thead>
        <tbody id="trade-table"></tbody>
    </table>

    <script>
        const layout = {
            title: 'Live Spread vs Mathematical Bounds',
            paper_bgcolor: '#161b22', plot_bgcolor: '#161b22',
            font: {color: '#c9d1d9'},
            xaxis: {showgrid: true, gridcolor: '#30363d', type: 'date', title: 'Time'},
            yaxis: {showgrid: true, gridcolor: '#30363d', title: 'Spread (₹)', zerolinecolor: '#8b949e'},
            margin: {l: 50, r: 20, t: 50, b: 50}
        };
        Plotly.newPlot('chart', [], layout);

        function triggerKillSwitch() {
            if(confirm("Are you sure you want to halt all trading engines?")) {
                fetch('/api/kill', {method: 'POST'}).then(() => alert("KILL SIGNAL SENT!"));
            }
        }

        let globalData = {math: [], trades: []};

        async function fetchWrapper() {
            try {
                const res = await fetch('/api/data');
                const data = await res.json();
                globalData = data;
                
                const statusEl = document.getElementById('sys-status');
                if (data.is_killed) {
                    statusEl.className = 'status-badge dead';
                    statusEl.innerText = 'SYSTEM HALTED';
                }
                forceUpdate();
            } catch (err) {}
        }

        function forceUpdate() {
            const selectedAsset = document.getElementById('asset-selector').value;
            
            // Filter math data by selected asset
            let filteredMath = globalData.math;
            if (selectedAsset !== "ALL") {
                filteredMath = globalData.math.filter(d => d.asset === selectedAsset);
            }

            if (filteredMath.length > 0) {
                const latest = filteredMath[filteredMath.length - 1];
                
                document.getElementById('m-signal').innerText = latest.signal;
                document.getElementById('m-spread').innerText = '₹' + latest.spread_short.toFixed(2);
                document.getElementById('m-ut').innerText = '₹' + latest.u_t.toFixed(2);
                document.getElementById('m-latency').innerText = (latest.latency_ns / 1000000).toFixed(3) + ' ms';

                // Use actual timestamps for the X axis
                const x = filteredMath.map(d => new Date(d.timestamp / 1000000));
                
                const trace1 = {x: x, y: filteredMath.map(d => d.spread_short), type: 'scatter', name: 'Actual Spread', line: {color: '#58a6ff', width: 2}};
                const trace2 = {x: x, y: filteredMath.map(d => d.u_t), type: 'scatter', name: 'Upper Threshold (u_t)', line: {color: '#ff7b72', dash: 'dash', width: 2}};
                const trace3 = {x: x, y: filteredMath.map(d => d.l_t), type: 'scatter', name: 'Lower Threshold (l_t)', line: {color: '#3fb950', dash: 'dash', width: 2}};
                
                Plotly.react('chart', [trace1, trace2, trace3], layout);
            }

            if (globalData.trades.length > 0) {
                let html = '';
                [...globalData.trades].reverse().forEach(t => {
                    html += `<tr>
                        <td style="color:#58a6ff;"><strong>${t.asset}</strong></td>
                        <td style="color:#3fb950;">${t.status}</td>
                        <td>${t.signal}</td>
                        <td>${t.qty}</td>
                        <td>₹${t.avg_spot_price.toFixed(2)}</td>
                        <td>₹${t.avg_fut_price.toFixed(2)}</td>
                    </tr>`;
                });
                document.getElementById('trade-table').innerHTML = html;
            }
        }

        setInterval(fetchWrapper, 500);
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    # Flask runs on the laptop
    app.run(host='0.0.0.0', port=5000)