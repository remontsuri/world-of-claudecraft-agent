"""C2 probe: farm->loot several corpses, inspect inventory, then call sell_junk
and report WHY copper does/doesn't change. Distinguishes:
 - no junk in inventory (world-dependent, honest SKIP)
 - junk present but sell_junk no-ops (== "no merchant nearby" server guard)
"""
from hierarchical_env import HierarchicalWoWEnv

env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=42)
obs, info = env.reset(seed=42)
k0 = info.get("kills", 0)

# farm+loot loop
for _ in range(8):
    # farm until a kill
    for _ in range(12):
        o, r, t, tr, i = env.step(0)
        if i.get("kills", 0) > k0:
            k0 = i.get("kills", 0); info = i; break
    else:
        continue
    # loot
    env.step(1)

inv = info.get("inventory") or []
print(f"kills={info.get('kills')} copper={info.get('copper')} inv_items={len(inv)}")
from collections import Counter
qc = Counter()
for it in inv:
    def_ = it.get("itemId")
    q = it.get("quality")
    qc[(def_, q)] += it.get("count", 1)
for (def_, q), c in qc.items():
    print(f"  {def_} quality={q} x{c}")

# try sell
c0 = info.get("copper", 0)
sold = env.base.sell_junk()
c1 = sold.get("copper", 0)
print(f"sell_junk: copper {c0} -> {c1}  delta={c1-c0}")
print("sell result keys:", list(sold.keys()))
env.close()
