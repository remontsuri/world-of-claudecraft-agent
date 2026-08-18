"""Probe: how many env.step(0) farm calls before the headless server dies?
This tells us the real stability budget of the low-level farm skill.
"""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT

env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=42)
obs, info = env.reset(seed=42)
# accept welcome quest so we have a target context (not required for farm crash test)
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

N = 300
for i in range(N):
    try:
        env.step(0)
        if i % 25 == 0:
            cur = None
            for aq in (env._last_info.get("quests", {}).get("active") or []):
                for ao in (aq.get("objectives") or []):
                    cur = ao.get("current")
            print(f"farm {i}: alive, q_current={cur}, pos={env._last_info.get('player_pos')}")
    except Exception as ex:
        print(f"DIED at farm call {i}: {ex!r}")
        break
env.close()
