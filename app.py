# app.py
import glob, io, json, os, sqlite3, threading, time, re
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, Response, send_file
import serial
import cv2

BAUD = 115200
PORT_GLOBS = ["/dev/ttyACM*", "/dev/ttyUSB*"]
SER_TIMEOUT = 1.5
LOCK = threading.Lock()

DB_PATH = "smarthome.db"
POLL_INTERVAL = 10  # seconds

app = Flask(__name__)

# ---- serial helpers ----
ser = None
latest = {
    "temp": None, "hum": None, "heater": 0, "fan": 0,
    "mode": "AUTO",
    "temp_on": 20.0, "temp_off": 24.0, "hum_on": 60.0, "hum_off": 60.0,
    "updated": None, "port": None, "raw": ""
}

def find_port():
    for pat in PORT_GLOBS:
        matches = sorted(glob.glob(pat))
        if matches:
            return matches[0]
    return None

def open_serial():
    global ser
    port = find_port()
    if not port:
        return None
    ser = serial.Serial(port, BAUD, timeout=SER_TIMEOUT)
    time.sleep(2.0)  # allow MCU reset
    latest["port"] = port
    return ser

def send_cmd(cmd):
    """Send a command and parse a STATUS line."""
    global ser
    with LOCK:
        if ser is None or not ser.is_open:
            if not open_serial():
                return None
        ser.reset_input_buffer()
        ser.write((cmd + "\n").encode("utf-8"))
        ser.flush()
        t0 = time.time()
        while time.time() - t0 < 2.0:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            if line.startswith("STATUS,"):
                latest["raw"] = line
                st = parse_status(line)
                if st:
                    latest.update(st)
                    latest["updated"] = time.time()
                return latest
        return None

def parse_status(line):
    # STATUS,temp=23.45,hum=51.20,heater=0,fan=1,mode=AUTO,temp_on=20.0,...
    try:
        parts = line.split(",")[1:]  # skip "STATUS"
        out = {}
        for p in parts:
            k, v = p.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k in ("temp", "hum", "temp_on", "temp_off", "hum_on", "hum_off"):
                out[k] = float("nan" if v.lower()=="nan" else v)
            elif k in ("heater","fan"):
                out[k] = int(v)
            elif k == "mode":
                out[k] = v.upper()
        return out
    except Exception:
        return None

# ---- database ----
def db_init():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS readings(
              ts INTEGER NOT NULL,
              temp REAL,
              hum REAL,
              heater INTEGER,
              fan INTEGER
            );
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_ts ON readings(ts);")

def db_insert(st):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO readings(ts,temp,hum,heater,fan) VALUES (?,?,?,?,?)",
            (int(st["updated"]), st.get("temp"), st.get("hum"), st.get("heater"), st.get("fan"))
        )

def db_get_since(since_epoch):
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT ts,temp,hum,heater,fan FROM readings WHERE ts>=? ORDER BY ts ASC",
            (since_epoch,)
        ).fetchall()
    return rows

# ---- poller ----
def poller():
    while True:
        try:
            st = send_cmd("GET")
            if st and st.get("updated"):
                db_insert(st)
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)

# ---- web UI ----
HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>ClimateOne</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root{--card:#f6f7fb;--muted:#666}
  body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:980px;margin:20px auto;padding:0 14px}
  h1{margin:.2rem 0}
  .sub{color:var(--muted);margin-bottom:12px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
  .card{background:var(--card);border:1px solid #e7e9ef;border-radius:16px;padding:16px;box-shadow:0 2px 8px rgba(0,0,0,.04)}
  .big{font-size:2.2rem;font-weight:700}
  .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .pill{border:1px solid #ddd;border-radius:999px;padding:4px 10px;background:#fff}
  button,input,select{padding:8px 10px;border-radius:10px;border:1px solid #ccc}
  label{font-size:.9rem;color:#333;margin-right:6px}
  img{max-width:100%;border-radius:12px;border:1px solid #ddd}
  .mono{font-family:ui-monospace,monospace}
  .sep{height:8px}
  canvas{background:#fff;border:1px solid #e7e9ef;border-radius:12px;padding:6px}
</style>
</head>
<body>
  <h1>Smart Home</h1>
  <div class="sub" id="meta">loading…</div>

  <div class="grid">
    <div class="card">
      <div class="row" style="justify-content:space-between">
        <div>
          <div>Temperature</div>
          <div class="big" id="t">--.- °C</div>
        </div>
        <div class="pill">Heater: <b id="heater">--</b></div>
      </div>
      <div class="sep"></div>
      <div class="row">
        <label>Mode</label>
        <select id="modeSel" onchange="setMode(this.value)">
          <option value="AUTO">AUTO</option>
          <option value="MANUAL">MANUAL</option>
        </select>
        <button onclick="setDev('heater',1)">Heater ON</button>
        <button onclick="setDev('heater',0)">Heater OFF</button>
      </div>
    </div>

    <div class="card">
      <div class="row" style="justify-content:space-between">
        <div>
          <div>Humidity</div>
          <div class="big" id="h">--.- %</div>
        </div>
        <div class="pill">Fan: <b id="fan">--</b></div>
      </div>
      <div class="sep"></div>
      <div class="row">
        <button onclick="setDev('fan',1)">Fan ON</button>
        <button onclick="setDev('fan',0)">Fan OFF</button>
      </div>
    </div>

    <div class="card">
      <div><b>Setpoints</b></div>
      <div class="sep"></div>
      <div class="row">
        <label>Temp ON</label><input id="sp_ton" type="number" step="0.1" style="width:90px">
        <label>Temp OFF</label><input id="sp_toff" type="number" step="0.1" style="width:90px">
      </div>
      <div class="row" style="margin-top:6px">
        <label>Hum ON</label><input id="sp_hon" type="number" step="0.1" style="width:90px">
        <label>Hum OFF</label><input id="sp_hoff" type="number" step="0.1" style="width:90px">
      </div>
      <div class="row" style="margin-top:8px">
        <button onclick="saveSetpoints()">Save</button>
      </div>
      <div class="mono" id="port" style="margin-top:8px;color:#555"></div>
    </div>

    <div class="card">
      <div class="row" style="justify-content:space-between">
        <div><b>Camera</b></div>
        <div><button onclick="snap()">Snapshot</button></div>
      </div>
      <div style="margin-top:8px"><img id="img" alt="snapshot will appear here"></div>
    </div>
  </div>

  <div class="sep"></div>
  <div class="card">
    <div class="row" style="justify-content:space-between">
      <b>History (last 6 hours)</b>
      <button onclick="loadHistory()">Refresh</button>
    </div>
    <div class="sep"></div>
    <canvas id="chartT" height="140"></canvas>
    <div class="sep"></div>
    <canvas id="chartH" height="140"></canvas>
  </div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script>
let chartT, chartH;

async function api(url, opts) {
  const r = await fetch(url, opts || {});
  const j = await r.json();
  if (!j.ok && j.ok !== undefined) throw new Error(j.error || "api error");
  return j;
}

function fmtTs(ts){return new Date(ts*1000).toLocaleTimeString();}

async function refresh() {
  try {
    const j = await api('/api/status');
    document.getElementById('t').textContent = (j.temp!=null && !Number.isNaN(j.temp)) ? j.temp.toFixed(2)+' °C' : '--.- °C';
    document.getElementById('h').textContent = (j.hum!=null && !Number.isNaN(j.hum)) ? j.hum.toFixed(2)+' %' : '--.- %';
    document.getElementById('heater').textContent = j.heater ? 'ON' : 'OFF';
    document.getElementById('fan').textContent = j.fan ? 'ON' : 'OFF';
    document.getElementById('modeSel').value = j.mode || 'AUTO';
    document.getElementById('sp_ton').value = j.temp_on?.toFixed(1) ?? '';
    document.getElementById('sp_toff').value = j.temp_off?.toFixed(1) ?? '';
    document.getElementById('sp_hon').value = j.hum_on?.toFixed(1) ?? '';
    document.getElementById('sp_hoff').value = j.hum_off?.toFixed(1) ?? '';
    document.getElementById('port').textContent = 'Port: ' + (j.port || '--') + (j.updated ? '   Updated: '+fmtTs(j.updated) : '');
    document.getElementById('meta').textContent = j.updated ? ('Last update: ' + fmtTs(j.updated)) : 'No data yet…';
  } catch(e) {
    document.getElementById('meta').textContent = 'Error contacting server';
    console.error(e);
  }
}

async function setMode(mode) {
  try { await api('/api/mode/'+mode, {method:'POST'}); refresh(); } catch(e){console.error(e);}
}

async function setDev(dev, state) {
  try { await api('/api/set/'+dev+'/'+state, {method:'POST'}); refresh(); } catch(e){console.error(e);}
}

async function saveSetpoints() {
  const body = {
    temp_on: parseFloat(document.getElementById('sp_ton').value),
    temp_off: parseFloat(document.getElementById('sp_toff').value),
    hum_on: parseFloat(document.getElementById('sp_hon').value),
    hum_off: parseFloat(document.getElementById('sp_hoff').value),
  };
  try {
    await api('/api/setpoints', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    refresh();
  } catch(e){ console.error(e); }
}

function snap(){ document.getElementById('img').src = '/snapshot.jpg?t='+Date.now(); }

async function loadHistory() {
  const r = await fetch('/api/history?minutes=360');
  const j = await r.json();
  const labels = j.ts.map(x => new Date(x*1000).toLocaleTimeString());
  const temp = j.temp, hum = j.hum;
  if (chartT) chartT.destroy();
  if (chartH) chartH.destroy();
  chartT = new Chart(document.getElementById('chartT'), {
    type:'line',
    data:{labels, datasets:[{label:'Temp (°C)', data: temp, tension:0.2, fill:false}]},
    options:{responsive:true, scales:{y:{beginAtZero:false}}}
  });
  chartH = new Chart(document.getElementById('chartH'), {
    type:'line',
    data:{labels, datasets:[{label:'Humidity (%)', data: hum, tension:0.2, fill:false}]},
    options:{responsive:true, scales:{y:{beginAtZero:false}}}
  });
}

refresh();
setInterval(refresh, 5000);
setTimeout(loadHistory, 1000);
</script>
</body>
</html>
"""

@app.route("/")
def home():
    return Response(HTML, mimetype="text/html")

@app.route("/api/status")
def api_status():
    # if we don't have a recent update, force a GET once
    if not latest.get("updated") or time.time() - latest["updated"] > POLL_INTERVAL*1.5:
        send_cmd("GET")
    out = {k: latest.get(k) for k in ["temp","hum","heater","fan","mode","temp_on","temp_off","hum_on","hum_off","updated","port"]}
    out["ok"] = True
    return jsonify(out)


@app.route("/api/mode/<mode>", methods=["POST"])
def api_mode(mode):
    mode = mode.upper()
    if mode not in ("AUTO", "MANUAL"):
        return jsonify({"ok": False, "error": "bad mode"}), 400
    st = send_cmd("MODE," + mode)
    d = {"ok": bool(st)}
    if st:
        d.update({
            "mode":   latest.get("mode"),
            "heater": latest.get("heater"),
            "fan":    latest.get("fan"),
            "temp":   latest.get("temp"),
            "hum":    latest.get("hum"),
        })
    return jsonify(d)



@app.route("/api/set/<dev>/<state>", methods=["POST"])
def api_set(dev, state):
    dev = dev.lower()
    if dev not in ("heater", "fan"):
        return jsonify({"ok": False, "error": "bad device"}), 400
    state = '1' if state == '1' else '0'
    st = send_cmd("SET," + dev + "," + state)
    d = {"ok": bool(st)}
    if st:
        d.update({
            "mode":   latest.get("mode"),
            "heater": latest.get("heater"),
            "fan":    latest.get("fan"),
            "temp":   latest.get("temp"),
            "hum":    latest.get("hum"),
        })
    return jsonify(d)

@app.route("/api/setpoints", methods=["POST"])
def api_setpoints():
    data = request.get_json(force=True, silent=True) or {}
    keys = {"temp_on":"temp_on","temp_off":"temp_off","hum_on":"hum_on","hum_off":"hum_off"}
    ok = True
    for k in keys:
        if k in data and isinstance(data[k], (int, float)):
            cmd = "SETPT,{},{}".format(k, data[k])
            if not send_cmd(cmd):
                ok = False
            time.sleep(0.05)
    st = send_cmd("GET")
    d = {"ok": ok and bool(st)}
    if st:
        d.update({
            "temp_on": latest.get("temp_on"),
            "temp_off": latest.get("temp_off"),
            "hum_on": latest.get("hum_on"),
            "hum_off": latest.get("hum_off"),
        })
    return jsonify(d)


@app.route("/api/history")
def api_history():
    minutes = float(request.args.get("minutes", "60"))
    since = int(time.time() - minutes*60)
    rows = db_get_since(since)
    ts, temp, hum, heater, fan = [], [], [], [], []
    for r in rows:
        ts.append(r[0]); temp.append(r[1]); hum.append(r[2]); heater.append(r[3]); fan.append(r[4])
    return jsonify({"ts": ts, "temp": temp, "hum": hum, "heater": heater, "fan": fan})

@app.route("/snapshot.jpg")
def snapshot():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return jsonify({"ok":False,"error":"camera not available"}), 500
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    time.sleep(0.1)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return jsonify({"ok":False,"error":"capture failed"}), 500
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        return jsonify({"ok":False,"error":"encode failed"}), 500
    return send_file(io.BytesIO(buf.tobytes()), mimetype="image/jpeg", as_attachment=False, download_name="snapshot.jpg")

def main():
    db_init()
    # kick one GET so UI has values quickly
    try: send_cmd("GET")
    except: pass
    threading.Thread(target=poller, daemon=True).start()
    app.run(host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
