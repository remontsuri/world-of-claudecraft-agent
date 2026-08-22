"""One-off Q-table sanitizer (run 2026-08-22).

The experience store carries POISONED legacy lessons from the era when the
bridge lied about quest phases:
  - return_to_giver / turn_in_quest with w=+5.0 and n=2971+ in buckets where
    the quest was NOT ready ('qs=ACTIVE|mob=1|...'). Those +5s came from the old
    reward path crediting quest completion on every nav leg while the buggy
    snapshot said READY_TO_TURN_IN. The agent still lives in these buckets, so
    Q(return)=+5 dominates every decision -> it circles between givers instead
    of fighting/farming.

Fix: clamp any walking-skill weight that is implausibly high in a non-ready
bucket down to a small positive value, and zero their visit counts so the
count-based exploration bonus treats them as untried again. Keep everything
else (combat/loot/sell lessons are honest).
"""
import json

PATH = r"D:\world-of-claudecraft\python\experience_autonomous.json"

d = json.load(open(PATH, encoding="utf-8"))
weights = d["weights"]  # [[bucket, action], w]
counts = d["counts"]

clamped = 0
zeroed_counts = 0
for entry in weights:
    key, w = entry
    bucket, action = key[0], key[1]
    if action not in ("return_to_giver", "turn_in_quest"):
        continue
    if "qs=ACTIVE" in bucket or "qs=NONE" in bucket:
        if w > 1.0:
            entry[1] = 0.2
            clamped += 1
            ck = [c for c in counts if c[0] == key[0] and c[1] == key[1]]
            for c in ck:
                c[1] = 0
                zeroed_counts += 1

json.dump(d, open(PATH, "w", encoding="utf-8"), ensure_ascii=False)
print(f"clamped {clamped} poisoned walking-skill weights; reset {zeroed_counts} counts")
