"""READ-ONLY re-verification after fixes.

B2: memory persistence — save() writes weights as a LIST of [key,value] pairs;
    _load() must parse that (previously called .items() on a list -> swallowed
    AttributeError -> memory always started EMPTY).
B3: count-based exploration bonus — must key on the REAL (bucket, action). The
    bonus should favour a never-tried action over a heavily-tried one at equal
    weight. Previously keyed on ("explore", action) -> constant bonus -> no-op.
"""

import os
import random
import tempfile

from memory import ExperienceStore, _bucket
from policy import _softmax_sample

print("=== B2: does ExperienceStore persist across reload? ===")
tmp = os.path.join(tempfile.gettempdir(), "woc_persist_probe.json")
if os.path.exists(tmp):
    os.remove(tmp)

st = ExperienceStore(path=tmp)
s_far = {"hp_frac": 1.0, "quest_status": "ACTIVE", "distance_to_giver": 300.0}
s_next = {"hp_frac": 1.0, "quest_status": "ACTIVE", "distance_to_giver": 250.0}
st.update(s_far, "return_to_giver", 1.25, next_state=s_next)
st.update(s_far, "farm", -3.0, next_state=s_far)
st.save()

b = _bucket(s_far)
print(f"  bucket            : {b}")
print(f"  in-process weights: return={st.value(b, 'return_to_giver'):+.4f} "
      f"farm={st.value(b, 'farm'):+.4f}")

st2 = ExperienceStore(path=tmp)
print(f"  RELOADED weights  : return={st2.value(b, 'return_to_giver'):+.4f} "
      f"farm={st2.value(b, 'farm'):+.4f}")
print(f"  reloaded entries  : weights={len(st2.weights)} counts={len(st2.counts)} "
      f"experiences={len(st2.experiences)}")
persisted = (len(st2.weights) == len(st.weights) and len(st.weights) > 0
             and abs(st2.value(b, "farm") - st.value(b, "farm")) < 1e-6)
print(f"  >> B2 FIXED (persistence survives reload): {persisted}")

print("\n=== B3: does the exploration bonus favour the untried action? ===")
# equal weights, but 'farm' tried 2000x in this bucket, 'gather' never tried
for _ in range(2000):
    st.counts[(b, "farm")] += 1
w = {"farm": 0.0, "gather": 0.0}
n = 20000
random.seed(7)
c = {"farm": 0, "gather": 0}
for _ in range(n):
    c[_softmax_sample(w, 1.2, counts=st.counts, bucket=b)] += 1
pf, pg = c["farm"] / n, c["gather"] / n
print(f"  counts: farm={st.counts[(b, 'farm')]}  gather={st.counts.get((b, 'gather'), 0)}")
print(f"  sampled P(farm)={pf:.3f}  P(gather)={pg:.3f}")
print(f"  >> B3 FIXED (untried 'gather' now preferred): {pg > pf + 0.05}")

# and farm must remain POSSIBLE even after a strong negative lesson (user rule)
w2 = {"farm": -5.0, "return_to_giver": 1.0, "gather": 0.0}
c2 = {k: 0 for k in w2}
for _ in range(n):
    c2[_softmax_sample(w2, 1.2, counts=st.counts, bucket=b)] += 1
p_farm = c2["farm"] / n
print(f"\n  after strong negative farm lesson: P(farm|far)={p_farm:.4f}")
print(f"  >> farm stays POSSIBLE (P>0, not hard-forbidden): {p_farm > 0.0}")

os.remove(tmp)
print("\n=== END ===")
