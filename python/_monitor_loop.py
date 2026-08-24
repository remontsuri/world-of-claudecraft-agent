import json, time, sys, collections, os

LOG = "autonomous_log.jsonl"
BRIDGE = "http://127.0.0.1:8791/"
PID_FILE = "play_autonomous.lock"

def post(p, timeout=20):
    try:
        import urllib.request
        raw = urllib.request.urlopen(urllib.request.Request(BRIDGE, data=json.dumps(p).encode(), headers={"Content-Type":"application/json"}), timeout=timeout)
        return json.load(raw)
    except Exception as e:
        return {"_err": repr(e)}

def get_pid():
    try:
        return open(PID_FILE).read().strip()
    except Exception:
        return None

def monitor(rounds=40, interval=15):
    seen = 0
    for r in range(rounds):
        pid = get_pid()
        counts = collections.Counter()
        verdicts = {a: collections.Counter() for a in ("return_to_giver","turn_in_quest","accept_quest")}
        env_err = 0
        last = None
        try:
            with open(LOG, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try: d = json.loads(line)
                    except Exception: continue
                    if pid and str(d.get("pid")) != str(pid): continue
                    a = d.get("action")
                    if a in verdicts:
                        counts[a]+=1
                        verdicts[a][d.get("verdict")]+=1
                    if d.get("kind")=="ENV_ERROR": env_err+=1
                    last = d
        except FileNotFoundError:
            pass
        # live player status
        st = post({"action":"snapshot"}, 10)
        info = st.get("info",{}) or {}
        pl = info.get("player",{}) or {}
        print(f"\n=== t+{(r+1)*interval}s | agent_pid={pid} | steps_tracked={sum(counts.values())} env_err={env_err} ===")
        for a in ("return_to_giver","turn_in_quest","accept_quest"):
            if counts[a]:
                print(f"  {a}: n={counts[a]} {dict(verdicts[a])}")
        print(f"  player: dead={pl.get('dead')} hp={pl.get('hp')}/{pl.get('maxHp')} pos={info.get('player_pos')}")
        if last:
            print(f"  last: {last.get('action')} v={last.get('verdict')} kind={last.get('kind')} dist={last.get('dist')} tstatus={last.get('quest_status')}")
        sys.stdout.flush()
        if r < rounds-1:
            time.sleep(interval)

if __name__ == "__main__":
    monitor()
