"""connectome_dashboard.py — Connectome-OS style live dashboard for the fly brain.

Shows live spike raster + group rates from the running LIF engine.
Pattern from Connectome-OS: watch structure as it fires, no AGI claims.
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# Engine is injected via set_engine()
ENGINE = None
HISTORY = []          # list of (t, spike_count, action, group_rates)
MAX_HISTORY = 600     # 60s at 10Hz
RATE_WINDOW = 10      # steps for rate calc


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/state":
            # Aggregate last N points into a raster for the UI
            state = {
                "witness": getattr(ENGINE, "_witness", "static"),
                "neurons": getattr(ENGINE, "n_neurons", 0),
                "history": list(HISTORY[-300:]),
                "total_spikes": sum(h[1] for h in HISTORY),
                "rate": sum(h[1] for h in HISTORY[-RATE_WINDOW:]) / max(len(HISTORY[-RATE_WINDOW:]), 1),
            }
            self._send(200, json.dumps(state).encode())
        elif self.path == "/" or self.path == "/index.html":
            html = PAGE
            self._send(200, html.encode(), "text/html")
        else:
            self._send(404, b"{}")


PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Connectome OS — WoC Fly Brain</title>
<style>
body{background:#0d1117;color:#c9d1d9;font-family:ui-monospace,monospace;margin:0;padding:16px}
h1{font-size:15px;color:#58a6ff;margin:0 0 4px}
.banner{background:#161b22;border:1px solid #30363d;padding:8px 12px;border-radius:6px;font-size:12px;margin-bottom:12px}
.banner .live{color:#3fb950;font-weight:bold}
#raster{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:10px;margin-bottom:12px}
#raster canvas{width:100%;height:140px;display:block;background:#0d1117}
#groups{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.g{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:8px 12px;font-size:12px}
.g b{display:block;font-size:18px}
.g .n{color:#8b949e;font-size:10px}
.stat{display:inline-block;margin-right:16px;font-size:12px}
.stat b{color:#58a6ff}
</style></head><body>
<h1>Connectome OS — engine=torch-lif substrate=male-cns-v1.0</h1>
<div class="banner"><span class="live">LIVE</span> <span id="witness">connecting…</span></div>
<div id="raster"><canvas id="cv" width="900" height="140"></canvas></div>
<div id="groups"></div>
<div><span class="stat">neurons <b id="n"></b></span><span class="stat">rate <b id="rate">0</b> sp/step</span><span class="stat">total <b id="total">0</b></span><span class="stat">action <b id="action">—</b></span></div>
<script>
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
const GROUPS=['DNg13','DNp01','DNg56','DNg30'];
async function tick(){
  try{
    const r=await fetch('/api/state');const s=await r.json();
    document.getElementById('witness').textContent='witness='+s.witness+' n='+s.neurons+' syn=26,028,386';
    document.getElementById('n').textContent=s.neurons;
    document.getElementById('total').textContent=s.total_spikes;
    document.getElementById('rate').textContent=s.rate.toFixed(1);
    // raster
    ctx.clearRect(0,0,cv.width,cv.height);
    const h=s.history;if(!h.length)return;
    const maxSpikes=Math.max(...h.map(x=>x[1]),1);
    h.forEach((p,i)=>{
      const x=(i/h.length)*cv.width;
      const y=cv.height-(p[1]/maxSpikes)*cv.height;
      ctx.fillStyle=p[2]===6?'#30363d':'#3fb950';
      ctx.fillRect(x,y,2,Math.max(2,cv.height-y));
    });
    // groups
    const g=document.getElementById('groups');
    g.innerHTML=GROUPS.map(nm=>{
      const last=h[h.length-1];
      const v=last&&last[3]?last[3][nm]||0:0;
      return `<div class="g"><span class="n">${nm}</span><b>${v.toFixed(2)}</b><span class="n">Hz</span></div>`;
    }).join('');
    const last=h[h.length-1];
    document.getElementById('action').textContent=last?last[2]:'—';
  }catch(e){document.getElementById('witness').textContent='offline: '+e.message}
}
setInterval(tick,500);tick();
</script></body></html>"""


def set_engine(engine):
    """Inject engine + start the sampling thread."""
    global ENGINE
    ENGINE = engine
    engine._witness = hex(int(time.time() * 1000))[-8:]


def sample_loop(interval=0.5):
    """Pull engine state and append to HISTORY (called by caller)."""
    if ENGINE is None:
        return
    spikes = ENGINE.last_spikes if hasattr(ENGINE, "last_spikes") else None
    action = ENGINE.last_action if hasattr(ENGINE, "last_action") else 6
    rates = getattr(ENGINE, "group_rates", None)
    count = int(spikes.sum().item()) if spikes is not None else 0
    HISTORY.append((time.time(), count, action, rates))
    if len(HISTORY) > MAX_HISTORY:
        del HISTORY[:-MAX_HISTORY]


def start_server(port=8792):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    print(f"[dashboard] Connectome-OS style dashboard: http://127.0.0.1:{port}")
    return srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8792)
    args = ap.parse_args()
    start_server(args.port)
    print("[dashboard] Running standalone (no engine).")
    while True:
        time.sleep(1)
