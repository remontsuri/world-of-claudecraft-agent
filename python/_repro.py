import os, sys, time, threading, faulthandler
faulthandler.dump_traceback_later(55, exit=True)
sys.path.insert(0, r"D:\world-of-claudecraft\python")
os.chdir(r"D:\world-of-claudecraft\python")

import socket as _sock

def health_probe():
    """Poll /health in a thread; if it stops answering, the bridge is globally stuck."""
    while True:
        try:
            s = _sock.create_connection(("127.0.0.1", 8791), timeout=3.0)
            s.settimeout(3.0)
            s.sendall(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1:8791\r\nConnection: close\r\n\r\n")
            s.recv(4096)
            s.close()
            print(f"[health {time.strftime('%H:%M:%S')}] OK", flush=True)
        except Exception as e:
            print(f"[health {time.strftime('%H:%M:%S')}] FAIL {type(e).__name__}: {e}", flush=True)
        time.sleep(4)

threading.Thread(target=health_probe, daemon=True).start()

from browser_env import BrowserEnv
env = BrowserEnv()
print("env initialized, starting explores", flush=True)
for i in range(40):
    t0 = time.time()
    try:
        env.explore_walk(10)
        dt = time.time() - t0
        print(f"[{i}] OK explore {dt:.2f}s", flush=True)
    except Exception as e:
        print(f"[{i}] EXC {type(e).__name__}: {e}", flush=True)
        # if it's a bridge error we can keep going
        continue
print("REPRO DONE", flush=True)
