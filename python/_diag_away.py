"""READ-ONLY: does _navigate_to_coord actually move the player ~400u away, or
does it fail (return False) and leave the player near the giver?

experiment_b2.force_far() walks AWAY from the giver to (giver + dir*400) up to 4
times, but the eval seeds still report "never reached far". Either:
  (a) navigation returns False early (no_progress>=30 guard), or
  (b) the world is small/blocked and 400u is unreachable, or
  (c) player_pos isn't what we think.

Measure it directly on the eval seeds.
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


for seed in (4242, 5353, 6464):
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=6000, seed=seed)
    env.reset(seed=seed)
    if not accept_welcome(env):
        print(f"seed={seed}: no giver")
        env.close()
        continue
    q = QuestCapability(env).find_active_quest()
    gx, gz = (q["turnInNpc"]["x"], q["turnInNpc"]["z"])
    print(f"\nseed={seed}: giver=({gx:.1f},{gz:.1f})")
    for leg in range(4):
        px, pz = env._last_info.get("player_pos", [0, 0])
        dx, dz = px - gx, pz - gz
        n = (dx * dx + dz * dz) ** 0.5 or 1.0
        dx, dz = dx / n, dz / n
        tx, tz = gx + dx * 400.0, gz + dz * 400.0
        ok = env._navigate_to_coord(tx, tz, max_steps=400)
        pf, pzf = env._last_info.get("player_pos", [0, 0])
        d = ((gx - pf) ** 2 + (gz - pzf) ** 2) ** 0.5
        print(f"  leg{leg}: nav_ok={ok} player=({pf:.1f},{pzf:.1f}) dist_to_giver={d:.1f}")
        if d > 80:
            print("    >> FAR reached")
            break
    env.close()

print("done")
