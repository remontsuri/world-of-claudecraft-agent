import sys, os, time, json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(REPO, "python", "autonomous_log.jsonl")
LOCK = os.path.join(REPO, "python", "play_autonomous.lock")
BRIDGE = "http://127.0.0.1:8791/health"

def bridge_up():
    try:
        import urllib.request
        j = json.load(urllib.request.urlopen(BRIDGE, timeout=3))
        return j
    except Exception as e:
        return {"error": str(e)}

def last_step():
    try:
        with open(LOG, encoding="utf-8") as f:
            for ln in f.readlines()[-1:]:
                return json.loads(ln)
    except Exception:
        return None

def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "monitor"
    h = bridge_up()
    print(f"[{tag}] HEALTH {h}")
    print(f"[{tag}] lock {'-> ' + open(LOCK).read().strip() if os.path.exists(LOCK) else 'NO LOCK'}")
    d = last_step()
    if d:
        print(f"[{tag}] step={d.get('step')} pid={d.get('pid')} action={d.get('action')} "
              f"hp={d.get('hp_frac') or d.get('hp')} reward={d.get('reward')} verdict={d.get('verdict')}")
        print(f"[{tag}]   quest_status={d.get('quest_status')} dist={d.get('dist')} bucket={d.get('bucket_after')}")
    print(f"[{tag}] log mtime {time.ctime(os.path.getmtime(LOG))}")

if __name__ == "__main__":
    main()
