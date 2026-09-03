"""Bridge readiness check — polls /health until page:true, game:true."""
import sys
import time
import urllib.request

URL = "http://localhost:8791/health"
TIMEOUT = 60  # seconds

def main():
    start = time.time()
    while time.time() - start < TIMEOUT:
        try:
            with urllib.request.urlopen(URL, timeout=2) as r:
                data = r.read().decode()
                if '"page":true' in data and '"game":true' in data:
                    print("BRIDGE_READY")
                    sys.exit(0)
        except Exception:
            pass
        time.sleep(1)
    print("BRIDGE_TIMEOUT")
    sys.exit(1)

if __name__ == "__main__":
    main()
