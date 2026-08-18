"""C3 probe: harvestable node spawn + harvest_node cmd in headless warrior.
Checks whether nodes appear in info['gather']['nearbyNodes'] at all (and at
what distance), and whether harvest_node() actually returns a harvest outcome.
Fast: only reset + one cmd per seed, no farm loops.
"""
from wow_env import WoWClassicEnv

for seed in [7, 42, 1, 100, 2024]:
    env = WoWClassicEnv(player_class="warrior", max_steps=500)
    obs, info = env.reset(seed=seed)
    gather = info.get("gather") or {}
    nodes = gather.get("nearbyNodes") or []
    hnodes = [n for n in nodes if n.get("harvestable")]
    print(f"seed={seed}: gather_keys={list(gather.keys())} nodes={len(nodes)} harvestable={len(hnodes)}")
    if hnodes:
        n0 = hnodes[0]
        print(f"  node id={n0.get('id')} mat={n0.get('materialId')} dist={n0.get('dist')} harvestable={n0.get('harvestable')}")
        out = env.harvest_node(str(n0.get("id")), False)
        print(f"  harvest_node ok={out.get('ok')} outcome={out.get('outcome')}")
    env.close()
