# app.py
import re, time, threading, glob
from datetime import datetime
from flask import Flask, jsonify, Response
import serial

BAUD = 115200
SCAN_GLOBS = ["/dev/ttyACM*", "/dev/ttyUSB*"]  # typical Arduino ports
READ_TIMEOUT_S = 1.5
RECONNECT_DELAY_S = 3

status = {
    "temp": None,
    "hum": None,
    "heater": None,   # True/False
    "fan": None,      # True/False
    "last_line": "",
    "port": None,
    "updated": None,
}

def find_port():
    for pattern in SCAN_GLOBS:
        for path in sorted(glob.glob(pattern)):
            return path
    return None

def parse_line(line):
    # Examples to match:
    # Temp C: 23.45 | Hum %: 55.10 | HEAT(A7/A8): OFF | FAN(A2/A3): ON
    m_t = re.search(r"Temp C:\s*(-?\d+(?:\.\d+)?)", line, re.I)
    m_h = re.search(r"Hum %:\s*(-?\d+(?:\.\d+)?)", line, re.I)
    m_heat = re.search(r"HEAT.*?:\s*(ON|OFF)", line, re.I)
    m_fan  = re.search(r"FAN.*?:\s*(ON|OFF)", line, re.I)

    out = {}
    if m_t: out["temp"] = float(m_t.group(1))
    if m_h: out["hum"] = float(m_h.group(1))
    if m_heat: out["heater"] = (m_heat.group(1).upper() == "ON")
    if m_fan:  out["fan"] = (m_fan.group(1).upper() == "ON")
    return out

def reader_loop():
    ser = None
    while True:
        try:
            if ser is None or not ser.is_open:
                port = find_port()
                if not port:
                    time.sleep(RECONNECT_DELAY_S)
                    continue
                ser = serial.Serial(port, BAUD, timeout=READ_TIMEOUT_S)
                time.sleep(2.0)  # let board reset
                status["port"] = port

            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            parsed = parse_line(line)
            if parsed:
                # only overwrite fields we actually parsed this line
                for k, v in parsed.items():
                    status[k] = v
                status["last_line"] = line
                status["updated"] = time.time()
        except Exception as e:
            # drop the port and retry
            try:
                if ser:
                    ser.close()
            except:
                pass
            ser = None
            status["port"] = None
            time.sleep(RECONNECT_DELAY_S)

app = Flask(__name__)

HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Smart Home Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --card: #f7f7f8; --text: #111; --muted:#666; --ok:#128c7e; --bad:#b00020; }
  body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;color:var(--text)}
  h1{margin:8px 0 4px}
  .sub{color:var(--muted);font-size:.9rem;margin-bottom:16px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
  .card{background:var(--card);border-radius:16px;padding:16px;border:1px solid #e7e7ea;box-shadow:0 2px 8px rgba(0,0,0,.04)}
  .big{font-size:2.2rem;font-weight:700}
  .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .pill{border:1px solid #ddd;border-radius:999px;padding:4px 10px}
  .ok{color:var(--ok)} .bad{color:var(--bad)}
  .mono{font-family:ui-monospace,monospace}
  footer{margin-top:14px;color:var(--muted);font-size:.9rem}
</style>
</head>
<body>
  <h1>Smart Home</h1>
  <div class="sub" id="meta">loading…</div>

  <div class="grid">
    <div class="card">
      <div>Temperature</div>
      <div class="big" id="t">--.- °C</div>
      <div class="row"><span class="pill mono">Heater: <span id="heat">--</span></span></div>
    </div>
    <div class="card">
      <div>Humidity</div>
      <div class="big" id="h">--.- %</div>
      <div class="row"><span class="pill mono">Fan: <span id="fan">--</span></span></div>
    </div>
    <div class="card">
      <div>Port</div>
      <div class="mono" id="port">--</div>
      <div class="mono" id="line" style="margin-top:6px;white-space:pre-wrap;word-break:break-word;color:#444"></div>
    </div>
  </div>

  <footer>Auto-refreshing every 2s. Values come from Arduino serial output.</footer>

<script>
async function refresh() {
  try {
    const r = await fetch('/api/status');
    const j = await r.json();

    const t = (j.temp!==null && j.temp!==undefined) ? j.temp.toFixed(2)+' °C' : '--.- °C';
    const h = (j.hum!==null && j.hum!==undefined) ? j.hum.toFixed(2)+' %'  : '--.- %';
    document.getElementById('t').textContent = t;
    document.getElementById('h').textContent = h;

    const heat = j.heater===true ? 'ON' : (j.heater===false ? 'OFF' : '--');
    const fan  = j.fan===true ? 'ON' : (j.fan===false ? 'OFF' : '--');
    document.getElementById('heat').textContent = heat;
    document.getElementById('fan').textContent = fan;

    document.getElementById('port').textContent = j.port || '--';
    document.getElementById('line').textContent = j.last_line || '';

    const when = j.updated ? new Date(j.updated*1000) : null;
    document.getElementById('meta').textContent =
      (when ? 'Last update: '+when.toLocaleTimeString() : 'No data yet…');
  } catch(e) {
    document.getElementById('meta').textContent = 'Error contacting server';
    console.error(e);
  }
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""

@app.route("/")
def home():
    return Response(HTML, mimetype="text/html")

@app.route("/api/status")
def api_status():
    # copy to avoid races
    s = {k: status.get(k) for k in ["temp","hum","heater","fan","last_line","port","updated"]}
    s["ok"] = bool(s["updated"])
    return jsonify(s)

def main():
    th = threading.Thread(target=reader_loop, daemon=True)
    th.start()
    app.run(host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
