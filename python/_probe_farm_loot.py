"""Probe: does interleaving loot (env.step(1)) between farm calls prevent the
server death at ~250 farm calls? Loot clears corpses, which may be the state
the server accumulates until it dies."""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT

env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=42)
obs, info = env.reset(seed=42)
giver = None
for _ in range(24):
    env.base.step(ACT_FORWARD); env.base.step(ACT_TURN_LEFT)
    near = env._last_info.get("nearby") or []
    g = [e for e in near if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId"))]
    if g:
        giver = g[0]; break
if giver:
    qid = (giver.get("questIds") or [None])[0]
    env._navigate_to_coord(giver.get("x"), giver.get("z"), max_steps=80)
    env.base.accept_quest(str(qid))
    env._last_info = env.base.accept_quest(str(qid))

N = 400
farm_calls = 0
for i in range(N):
    try:
        if i % 10 == 9:
            env.step(1)  # loot every 10th
        else:
            env.step(0); farm_calls += 1
        if i % 50 == 0:
            cur = None
            for aq in (env._last_info.get("quests", {}).get("active") or []):
                for ao in (aq.get("objectives") or []):
                    cur = ao.get("current")
            print(f"iter {i}: alive, farm_calls={farm_calls}, q_current={cur}")
    except Exception as ex:
        print(f"DIED at iter {i} (farm_calls={farm_calls}): {ex!r}")
        break
env.close()
