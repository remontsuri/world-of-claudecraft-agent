"""READ-ONLY: did navigation close the distance, or did DEATH+RESPAWN teleport us?

_diag_navverify.py showed dist 97.4 -> 4.0 in a SINGLE return_to_giver call with
reward -2.6327. Decomposing that reward:
    dist_progress  93.4 * 0.02 = +1.868
    success_bonus              = +0.500
    death                      = -5.000
                                 -------
                                 -2.632   <- exact match

So the agent DIED during that call, and respawn almost certainly teleported it
back to the graveyard/start near the giver. That would mean the "arrival" was NOT
navigation, and dist_progress would be rewarding death — a false lesson.

This probe separates the two mechanisms:
  P1. Pure navigation, NO combat: walk away from the giver with plain forward
      steps at full HP, then navigate back. Track deaths — must stay 0.
      If distance closes with deaths==0, navigation genuinely works.
  P2. Log the death/respawn signature: deaths counter + player_pos before/after,
      to confirm whether respawn relocates the player.
"""

import sys

from hierarchical_env import (HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT,
                              ACT_TURN_RIGHT)
from quest_capability import QuestCapability
from world_state import build_world_state

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42


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


def snap(env):
    info = env._last_info
    ws = build_world_state(info)
    p = info.get("player", {}) or {}
    return {
        "dist": ws["distance_to_giver"],
        "deaths": ws["deaths"],
        "hp": ws["hp_frac"],
        "pos": info.get("player_pos"),
        "combat": ws["in_combat"],
    }


def giver_xz(env):
    for q in (env._last_info.get("quests", {}).get("active") or []):
        t = q.get("turnInNpc") or {}
        if t.get("x") is not None:
            return t["x"], t["z"]
    return None, None


env = HierarchicalWoWEnv(player_class="warrior", max_steps=6000, seed=SEED)
env.reset(seed=SEED)
print(f"=== DEATH vs NAVIGATION seed={SEED} ===")

if not accept_welcome(env):
    print("no giver; abort")
    env.close()
    sys.exit(1)

gx, gz = giver_xz(env)
s0 = snap(env)
print(f"start: dist={s0['dist']:.1f} deaths={s0['deaths']} hp={s0['hp']:.2f} pos={s0['pos']}")
print(f"giver at ({gx:.1f}, {gz:.1f})")

# ---- P1: walk AWAY with plain movement (no farming -> no combat deaths) ----
print("\n--- P1a: walk away using plain forward (no combat) ---")
for i in range(4):
    env.base.step(ACT_TURN_RIGHT)
env._last_info = env.base.step(ACT_FORWARD)[4]
for i in range(120):
    env._last_info = env.base.step(ACT_FORWARD)[4]
s1 = snap(env)
print(f"  after 120 forward: dist={s1['dist']:.1f} deaths={s1['deaths']} "
      f"hp={s1['hp']:.2f} combat={s1['combat']} pos={s1['pos']}")

if s1["deaths"] > s0["deaths"]:
    print("  !! died while walking — cannot isolate navigation this way")

# ---- P1b: navigate back, deaths must not change ----
print("\n--- P1b: navigate back to giver (deaths must stay constant) ---")
before = snap(env)
arrived = env._navigate_to_coord(gx, gz, max_steps=200)
after = snap(env)
print(f"  arrived={arrived}")
print(f"  dist   {before['dist']:.1f} -> {after['dist']:.1f}  (closed {before['dist'] - after['dist']:+.1f})")
print(f"  deaths {before['deaths']} -> {after['deaths']}")
print(f"  hp     {before['hp']:.2f} -> {after['hp']:.2f}")
print(f"  pos    {before['pos']} -> {after['pos']}")

nav_clean = (after["deaths"] == before["deaths"]
             and after["dist"] < before["dist"] - 5)
print(f"\n  >> NAVIGATION genuinely closes distance without dying: {nav_clean}")

# ---- P2: what does a death/respawn actually do to position? ----
print("\n--- P2: death/respawn signature (farm until a death occurs) ---")
pre = snap(env)
died = False
for i in range(80):
    b = snap(env)
    try:
        env.step(0)   # farm
    except Exception as ex:
        print(f"  farm crashed at {i}: {ex!r}")
        break
    a = snap(env)
    if a["deaths"] > b["deaths"]:
        print(f"  DEATH at farm burst {i}:")
        print(f"    pos  {b['pos']} -> {a['pos']}")
        print(f"    dist {b['dist']:.1f} -> {a['dist']:.1f}   "
              f"({'RESPAWN MOVED PLAYER TOWARD GIVER' if a['dist'] < b['dist'] - 5 else 'position roughly kept'})")
        print(f"    hp   {b['hp']:.2f} -> {a['hp']:.2f}")
        died = True
        break
if not died:
    print("  no death observed in 80 farm bursts")

env.close()
print("\n=== END ===")
