"""READ-ONLY re-analysis of experiment_b3c_trace.csv: fix Variant B.

The B3-control M2 aggregated Q(return)/Q(farm) over ALL measured buckets, mixing
in buckets where return was never trained (Variant B from the user's review). Here
we restrict to rows whose initial_bucket is the far state we actually measured
(far=1) and compare Q(return) vs Q(farm) ONLY there — the honest test.

Also reports P(return|far) and P(farm|far) from raw counts (point #1).
"""

import csv
from collections import Counter

PATH = "experiment_b3c_trace.csv"
rows = []
with open(PATH, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        rows.append(r)

for phase in ("BEFORE", "AFTER"):
    pr = [r for r in rows if r["phase"] == phase and "far=1" in r["initial_bucket"]]
    n = len(pr)
    if n == 0:
        print(f"{phase}: no far-rows"); continue
    cnt = Counter(r["action"] for r in pr)
    ret = cnt.get("return_to_giver", 0)
    farm = cnt.get("farm", 0)
    # Q BEFORE this decision, restricted to far-rows
    q_ret = [float(r["Q_before_return"]) for r in pr if r["Q_before_return"] not in ("", None)]
    q_farm = [float(r["Q_before_farm"]) for r in pr if r["Q_before_farm"] not in ("", None)]
    qr = sum(q_ret)/len(q_ret) if q_ret else 0.0
    qf = sum(q_farm)/len(q_farm) if q_farm else 0.0
    # mean delta distance per action (restricted to far-rows)
    from collections import defaultdict
    dd = defaultdict(list)
    for r in pr:
        try:
            dd[r["action"]].append(float(r["dist_before"]) - float(r["dist_after"]))
        except ValueError:
            pass
    print(f"\n=== {phase} (far-rows only: {n}) ===")
    print(f"  P(return|far) = {ret}/{n} = {ret/n:.4f}")
    print(f"  P(farm|far)   = {farm}/{n} = {farm/n:.4f}")
    print(f"  Q(return) mean = {qr:+.4f}   Q(farm) mean = {qf:+.4f}   gap = {qr-qf:+.4f}")
    for a in dd:
        print(f"  Δdist[{a}] = {sum(dd[a])/len(dd[a]):+.2f}")
