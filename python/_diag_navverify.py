"""READ-ONLY verification that the patched _navigate_to_coord closes distance,
and that return_to_giver now produces a measurable positive dist_progress.

Checks:
  N1. drift far by real farming, then call return_to_giver repeatedly and log
      distance_to_giver before/after EACH call -> is there a monotone chain?
  N2. compute the reward each call would earn via reward.outcome_reward, to prove
      the positive signal comes from the MEASURED delta (dist_progress), not from
      a hard-coded "return is good" rule.
"""

import sys

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability
from world_state import build_world_state
from reward import outcome_reward
import quest_skill

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


def dist(env):
    return build_world_state(env._last_info)["distance_to_giver"]


env = HierarchicalWoWEnv(player_class="warrior", max_steps=4000, seed=SEED)
env.reset(seed=SEED)
print(f"=== NAV FIX VERIFY seed={SEED} ===")

if not accept_welcome(env):
    print("no quest giver found; abort")
    env.close()
    sys.exit(1)
print(f"quest accepted, dist_to_giver={dist(env):.1f}")

# --- drift far by real farming (the honest way to reach far state) ---
print("\n--- drift far by real farming (skill 0 = farm) ---")
for i in range(60):
    if dist(env) > 90:
        break
    try:
        env.step(0)
    except Exception as ex:
        print(f"  farm crashed at {i}: {ex!r}")
        break
d_far = dist(env)
print(f"  after {i + 1} farm bursts: dist={d_far:.1f}  far={'YES' if d_far > 80 else 'no'}")

# --- N1/N2: repeated return_to_giver calls, measure each ---
print("\n--- return_to_giver chain (each call measured) ---")
ctx = {}
cap = QuestCapability(env)
q = cap.find_active_quest()
if q:
    ctx["quest"] = q

total = 0.0
for k in range(8):
    before_ws = build_world_state(env._last_info)
    d0 = before_ws["distance_to_giver"]
    try:
        res = quest_skill.return_to_giver(env, ctx)
    except Exception as ex:
        print(f"  [{k}] crashed: {ex!r}")
        break
    after_ws = build_world_state(env._last_info)
    d1 = after_ws["distance_to_giver"]
    verdict = "SUCCESS" if res == "SUCCESS" else "INCONCLUSIVE"
    r = outcome_reward(before_ws, after_ws, verdict, "OK")
    total += r
    arrow = "CLOSER" if d1 < d0 - 0.5 else ("same  " if abs(d1 - d0) <= 0.5 else "FARTHER")
    print(f"  [{k}] res={res:12s} dist {d0:7.1f} -> {d1:7.1f}  {arrow}  reward={r:+.4f}")
    if d1 < 6:
        print("      arrived at giver")
        break

print(f"\n  cumulative reward from the chain: {total:+.4f}")
print(f"  >> return_to_giver now MEASURABLE (positive from real dist delta): {total > 0}")

env.close()
print("\n=== END ===")
