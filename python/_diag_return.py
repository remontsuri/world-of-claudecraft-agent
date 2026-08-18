"""READ-ONLY diagnostic: is `return_to_giver` measurable at all?

Answers three factual questions before ANY code change:
  Q1. Does the active quest expose turnInNpc.x/z (and navPath)? If not,
      distance_to_giver is the 999.0 sentinel and dist_progress can NEVER fire.
  Q2. What is distance_to_giver right after accepting the welcome quest, and does
      it ever exceed the far=80 bucket threshold by plain farming?
  Q3. Does ONE return_to_giver call measurably decrease distance_to_giver?
      (print before/after distance + player_pos for every call)

No writes to memory, no policy learning, no Sim edits. Pure measurement.
"""

import json
import sys

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability
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
        g = [e for e in near if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId"))]
        if g:
            giver = g[0]
            break
    if not giver:
        return False
    qid = (giver.get("questIds") or [None])[0]
    env._navigate_to_coord(giver.get("x"), giver.get("z"), max_steps=80)
    env.base.accept_quest(str(qid))
    env._last_info = env.base.accept_quest(str(qid))
    return True


def quest_and_dist(env):
    """Return (quest, tNpc, distance) exactly as _world_state_dict computes it."""
    info = env._last_info
    for q in (info.get("quests", {}).get("active") or []):
        tNpc = q.get("turnInNpc") or {}
        if tNpc.get("x") is not None:
            px, pz = info.get("player_pos", [0, 0])
            d = ((tNpc["x"] - px) ** 2 + (tNpc["z"] - pz) ** 2) ** 0.5
            return q, tNpc, d
    # no usable turn-in coords -> the sentinel path
    active = (info.get("quests", {}).get("active") or [])
    return (active[0] if active else None), None, 999.0


def main():
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=SEED)
    obs, info = env.reset(seed=SEED)
    print(f"=== DIAG return_to_giver, seed={SEED} ===")

    ok = accept_welcome(env)
    print(f"[accept_welcome] {ok}")
    q, tNpc, d = quest_and_dist(env)

    # ---- Q1: turn-in NPC coordinates available? ----
    print("\n--- Q1: turnInNpc exposure ---")
    if q is None:
        print("  NO ACTIVE QUEST -> distance_to_giver is always the 999.0 sentinel.")
        env.close()
        return
    print(f"  quest id      : {q.get('id')}")
    print(f"  quest state   : {q.get('state')}")
    print(f"  objectives    : {json.dumps(q.get('objectives'), ensure_ascii=False)[:300]}")
    tn_raw = q.get("turnInNpc")
    print(f"  turnInNpc raw : {json.dumps(tn_raw, ensure_ascii=False)[:300] if tn_raw else None}")
    if tNpc is None:
        print("  >> VERDICT Q1: turnInNpc.x is None -> distance_to_giver == 999.0 CONSTANT.")
        print("     dist_progress can NEVER fire. `return` reward=0 is NOT a nav problem.")
    else:
        print(f"  turnInNpc x/z : {tNpc.get('x')} / {tNpc.get('z')}")
        print(f"  navPath len   : {len(tNpc.get('navPath') or [])}")
        print(f"  >> VERDICT Q1: coords available, distance = {d:.1f}")

    print(f"  player_pos    : {env._last_info.get('player_pos')}")
    print(f"  far(>80)?     : {d > 80}")

    # ---- Q2: does plain farming push us past far=80? ----
    print("\n--- Q2: drift by farming (30 farm skill calls) ---")
    dists = [d]
    for i in range(30):
        try:
            env.step(0)  # farm
        except Exception as ex:
            print(f"  farm[{i}] EXC {ex!r} -> stop")
            break
        _, _, dd = quest_and_dist(env)
        dists.append(dd)
        if i % 5 == 0:
            print(f"  farm[{i:2d}] dist={dd:7.1f} pos={env._last_info.get('player_pos')}")
    print(f"  dist min/max  : {min(dists):.1f} / {max(dists):.1f}")
    print(f"  reached far>80: {max(dists) > 80}")

    # ---- Q3: does ONE return_to_giver call reduce distance? ----
    print("\n--- Q3: return_to_giver measurable progress (5 calls) ---")
    for i in range(5):
        q_i, tn_i, d_before = quest_and_dist(env)
        pos_before = env._last_info.get("player_pos")
        try:
            res = quest_skill.return_to_giver(env, {"quest": q_i})
        except Exception as ex:
            print(f"  ret[{i}] EXC {ex!r}")
            break
        _, _, d_after = quest_and_dist(env)
        pos_after = env._last_info.get("player_pos")
        print(f"  ret[{i}] res={res:10s} dist {d_before:7.1f} -> {d_after:7.1f} "
              f"(delta={d_before - d_after:+.2f})  pos {pos_before} -> {pos_after}")

    env.close()
    print("\n=== DIAG END ===")


if __name__ == "__main__":
    main()
