"""Offline training: replay the historical autonomous_log through TD(0) into a
SEPARATE Q-table, then report quality vs the live table. Never touches
experience_autonomous.json — output goes to experience_offline.json for review.

Usage:
  python offline_train.py            # train + report
  python offline_train.py --merge    # after review, blend offline into live (0.3)
"""
import json
import os
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "autonomous_log.jsonl")
LIVE = os.path.join(HERE, "experience_autonomous.json")
OUT = os.path.join(HERE, "experience_offline.json")

GAMMA = 0.9
LR = 0.15
MIN_REWARD = -5.0


def bucket_of(row):
    """The log stores bucket_before already normalized — use it directly."""
    return row.get("bucket_before")


def main():
    rows = []
    with open(LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if "step" not in r or "action" not in r:
                continue
            # Filters: only honest outcomes from the POST-fix era.
            if "[MEASURE]" in (r.get("verdict") or ""):
                continue                      # frozen-eval, не обучение
            if r.get("kind") == "ENV_ERROR":
                continue                      # инфраструктура, reward 0
            b = bucket_of(r)
            if not b:
                continue
            rows.append(r)
    print(f"история: {len(rows)} пригодных шагов")

    # ---- TD(0) over the trajectory sequence ----
    q = defaultdict(float)
    n_visits = defaultdict(int)
    for i in range(len(rows) - 1):
        cur, nxt = rows[i], rows[i + 1]
        s, a = bucket_of(cur), cur["action"]
        r = max(min(cur.get("reward", 0.0), 5.0), MIN_REWARD)
        s2 = bucket_of(nxt)
        key = (s, a)
        n_visits[key] += 1
        old = q[key]
        # next value: max over known actions in s2 (approx: max of that bucket)
        best_next = max((v for (bs, ba), v in q.items() if bs == s2), default=0.0)
        q[key] = old + LR * (r + GAMMA * best_next - old)

    print(f"Q-ключей выучено: {len(q)}")

    # ---- quality report: top/bottom actions per phase ----
    by_action = defaultdict(list)
    for (s, a), v in q.items():
        qs = dict(p.split("=", 1) for p in s.split("|") if "=" in p)
        by_action[a].append((qs.get("hp", "?"), qs.get("qs", "?"), round(v, 3)))
    print("\n-- худшие связки (избегать):")
    flat = [(v, a, hp, qs) for a, lst in by_action.items()
            for (hp, qs, v) in lst]
    for v, a, hp, qs in sorted(flat)[:6]:
        print(f"  {v:+7.3f}  {a:16s} hp={hp:5s} qs={qs}")
    print("-- лучшие связки (повторять):")
    for v, a, hp, qs in sorted(flat, reverse=True)[:6]:
        print(f"  {v:+7.3f}  {a:16s} hp={hp:5s} qs={qs}")

    # ---- save ----
    out = {
        "trained_at": time.time(),
        "rows_used": len(rows),
        "gamma": GAMMA, "lr": LR,
        "q": [[list(k), v] for k, v in q.items()],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"\nсохранено: {OUT}")

    if "--merge" in sys.argv:
        live_d = json.load(open(LIVE, encoding="utf-8"))
        # live weights format: [[[bucket, action], value], ...]
        live_map = {json.dumps(k, ensure_ascii=False): v
                    for k, v in (live_d.get("weights") or [])}
        blended = 0
        for k, v in q.items():
            key = json.dumps(list(k), ensure_ascii=False)
            if key in live_map and abs(live_map[key]) > abs(v):
                continue                    # live уверен сильнее — не трогаем
            live_map[key] = live_map.get(key, 0.0) * 0.7 + v * 0.3
            blended += 1
        live_d["weights"] = [
            [json.loads(key), val] for key, val in live_map.items()]
        bak = LIVE + f".pre-merge-{int(time.time())}"
        import shutil
        shutil.copy2(LIVE, bak)
        with open(LIVE, "w", encoding="utf-8") as f:
            json.dump(live_d, f, ensure_ascii=False)
        print(f"MERGED {blended} ключей в живую таблицу (бэкап {bak})")


if __name__ == "__main__":
    main()
