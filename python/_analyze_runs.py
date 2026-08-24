import json, collections, os

def load(path):
    recs = []
    if not os.path.exists(path):
        return recs
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if "step" in r and "action" in r:
                recs.append(r)
    return recs

def runs_of(recs):
    runs, cur = [], [recs[0]]
    for prev, r in zip(recs, recs[1:]):
        if r["t"] < prev["t"] - 5:
            runs.append(cur); cur = []
        cur.append(r)
    runs.append(cur)
    return runs

for path in ["autonomous_log_prev.jsonl", "autonomous_log.jsonl"]:
    recs = load(path)
    if not recs:
        print(f"{path}: EMPTY/missing"); continue
    print(f"\n########## {path}: {len(recs)} records ##########")
    runs = runs_of(recs)
    # find runs with qprog gain and low deaths, and any run 100-200 steps
    for i, run in enumerate(runs):
        n = len(run)
        first, last = run[0], run[-1]
        dq = last.get('qprog',0)-first.get('qprog',0)
        dd = last['deaths']-first['deaths']
        if (100 <= n <= 250 and dq > 0) or (dd == 0 and dq >= 3):
            acts = collections.Counter(r["action"] for r in run)
            verd = collections.Counter(r["verdict"] for r in run)
            print(f"  run#{i}: {n} steps | qprog {first.get('qprog',0)}->{last.get('qprog',0)} ({dq:+d}) | deaths {dd:+d} | kills {last['kills']-first['kills']:+d}")
            print(f"    acts: {dict(acts.most_common(8))}")
            print(f"    verd: {dict(verd)}")
    # tail: last 3 records of the file
    print("  --- tail:")
    for r in recs[-3:]:
        print(f"    step={r['step']} t={r['t']} act={r['action']} qprog={r.get('qprog')} kills={r['kills']} deaths={r['deaths']} hp={r.get('hp')}")
