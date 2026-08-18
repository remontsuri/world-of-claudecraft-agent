"""READ-ONLY: can a plain-forward walk (no mob targeting) reliably reach far on
the eval seeds?

_diag_away showed _navigate_to_coord stalls at ~33u (no_progress guard). Farm
drift stalls at ~16.5u (no nearby mob). But _diag_navverify reached 59.8u with
120 plain ACT_FORWARD steps. A plain forward walk is the most deterministic way
to leave the giver. Measure how far plain-forward gets on 4242/5353/6464 and
whether it crosses 80.
"""

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability
from world_state import build_world_state
from memory import _bucket


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


for seed in (4242, 5353, 6464):
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=8000, seed=seed)
    env.reset(seed=seed)
    if not accept_welcome(env):
        print(f"seed={seed}: no giver")
        env.close()
        continue
    print(f"\nseed={seed}: plain-forward walk")
    reached = False
    for i in range(200):
        if "far=1" in _bucket(build_world_state(env._last_info)):
            print(f"  >> FAR at step {i}, dist={build_world_state(env._last_info)['distance_to_giver']:.1f}")
            reached = True
            break
        env.base.step(ACT_FORWARD)
        env._last_info = env.base.step(ACT_FORWARD)[4]
    if not reached:
        d = build_world_state(env._last_info)["distance_to_giver"]
        print(f"  not far after 200 forward; dist={d:.1f}")
    env.close()

print("done")
