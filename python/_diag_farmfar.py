"""READ-ONLY: can we reach a REAL game state (far AND mob nearby) by actual
farming, on the eval seeds?

B2's flaw: force_far walked AWAY from the giver with plain forward -> barren
state, no mobs, so return_to_giver could never show a benefit. B3 needs the
state: quest=ACTIVE, progress<required, distance_to_giver=far, mob_nearby=true.

Farm (env.step(0)) walks the player toward + attacks mobs, so it naturally
produces mob_nearby=true AND can drift far (seed 42 reached 97.4). But seed 4242
stalled at 16.5 when no mob was targetable. This probe tests a robust
farm-drift: farm; if the player stops moving (no mob), take a forward+turn step
to relocate, then farm again. Reports whether far+mob is reached per seed.
"""

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability
from world_state import build_world_state
from memory import _bucket

SEEDS = [4242, 5353, 6464]


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


def has_mob(info):
    near = info.get("nearby") or []
    return any((e.get("kind") == "mob" or e.get("type") == "mob") and not e.get("lootable")
               for e in near)


def is_far(info):
    return "far=1" in _bucket(build_world_state(info))


for seed in SEEDS:
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=8000, seed=seed)
    env.reset(seed=seed)
    if not accept_welcome(env):
        print(f"seed={seed}: no giver")
        env.close()
        continue
    reached = False
    stuck = 0
    prev = None
    for i in range(250):
        info = env._last_info
        if is_far(info) and has_mob(info):
            ws = build_world_state(info)
            print(f"  seed={seed}: FAR+MOB at iter {i}, dist={ws['distance_to_giver']:.1f}, "
                  f"prog={ws['quest_progress']}")
            reached = True
            break
        try:
            env.step(0)   # farm: walk to + attack nearest mob
        except Exception as ex:
            print(f"  seed={seed}: crashed at {i}: {ex!r}")
            break
        pos = env._last_info.get("player_pos")
        if prev and abs(pos[0] - prev[0]) < 0.1 and abs(pos[1] - prev[1]) < 0.1:
            stuck += 1
            if stuck >= 5:
                env.base.step(ACT_FORWARD)
                env.base.step(ACT_TURN_LEFT)
                stuck = 0
        else:
            stuck = 0
        prev = pos
    if not reached:
        ws = build_world_state(env._last_info)
        print(f"  seed={seed}: NOT far+mob after 250, dist={ws['distance_to_giver']:.1f} "
              f"mob={has_mob(env._last_info)}")
    env.close()

print("done")
