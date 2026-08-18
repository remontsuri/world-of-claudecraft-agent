"""Exact C1 from test_chains_headless.py (no direct request)"""
from hierarchical_env import HierarchicalWoWEnv
from verifiers_py import verify_skill

def farm_until_kill(env, max_farm=10):
    info = None
    k0 = env._last_info.get('kills', 0) if hasattr(env, '_last_info') else 0
    for _ in range(max_farm):
        obs, r, term, trunc, info = env.step(0)
        if info.get('kills', 0) > k0:
            return info
    return info

env = HierarchicalWoWEnv(player_class="warrior", max_steps=200, seed=42)
obs, info = env.reset(seed=42)
before = info
info = farm_until_kill(env)
print("kills=", info.get('kills'), "before kills=", before.get('kills'))
if not info or info.get('kills', 0) <= before.get('kills', 0):
    print("SKIP no kill"); env.close(); raise SystemExit
corp_id = None
for e in (info.get('nearby') or []):
    if e.get('type') == 'corpse' or e.get('kind') == 'corpse':
        corp_id = e.get('id'); break
print("corp_id=", corp_id)
before_loot = info
_, _, _, _, info = env.step(1)  # loot skill ONLY
print("after loot: inv=", len(before_loot.get('inventory',[])), "->", len(info.get('inventory',[])))
v = verify_skill('loot', {'before': before_loot, 'after': info, 'handle': corp_id})
print("verdict:", v)
env.close()
