"""READ-ONLY: trace farm-drift distance over 80 env.step(0) calls on seed 4242.

Earlier _diag_driftcheck showed seed 4242 stalls at dist=16.5 after 60 farm
bursts (never far). We want to see WHERE it stalls: does distance stop growing,
oscillate, or does the player stop moving entirely? Also confirm player_pos
actually changes per step (i.e. farm really moves the player).
"""

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability
from world_state import build_world_state


def accept_welcome(env):
    cap = QuestCapability(env)
    if cap.find_active_quest() is not None:
        return True
    giver = None
    for _ in range(24):
        env.base.step(ACT_FORWARD)
        env.base.step(ACT_TURN_LEFT)
        near = env._last_info.get("nearby") or []
        g = [e for e in near
             if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId"))]
        if g:
            giver = g[0]
            break
    if not giver:
        return False
    qid = (giver.get("questIds") or [None])[0]
    env._navigate_to_coord(giver.get("x"), giver.get("z"), max_steps=80)
    env._last_info = env.base.accept_quest(str(qid))
    return True


env = HierarchicalWoWEnv(player_class="warrior", max_steps=8000, seed=4242)
env.reset(seed=4242)
accept_welcome(env)
print("farm-drift trace seed=4242:")
prev = None
for i in range(81):
    ws = build_world_state(env._last_info)
    d = ws["distance_to_giver"]
    pos = env._last_info.get("player_pos")
    if i % 5 == 0 or i == 80:
        print(f"  step{i:3d} dist={d:7.1f} pos=({pos[0]:7.2f},{pos[1]:7.2f}) "
              f"moved={'Y' if prev is None or abs(pos[0]-prev[0])+abs(pos[1]-prev[1])>0.1 else 'N'}")
    prev = pos
    if d > 80:
        print(f"  >> FAR reached at step {i}")
        break
    if i < 80:
        try:
            env.step(0)
        except Exception as ex:
            print(f"  crashed at {i}: {ex!r}")
            break
env.close()
print("done")
