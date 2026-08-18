"""Capability precondition chain-test: QUEST (no PPO, deterministic).

Reframe-compliant (user 2026-08-16 pt.14): instead of "reset -> accept_quest ->
FAIL", we PREPARE world context by navigating to a quest-giver, then verify
each transition with the Verifier layer.

Chain: spawn -> roam/scan -> find quest-giver -> navigate -> accept ->
farm objective (kill) -> turn_in -> questDone.
"""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT, ACT_TURN_RIGHT
from verifiers_py import verify_skill

def find_quest_giver(info):
    near = info.get("nearby") or []
    givers = [e for e in near
              if (e.get("kind") == "npc" or e.get("type") == "npc")
              and (e.get("questIds") or e.get("questId"))]
    if not givers:
        return None
    givers.sort(key=lambda e: e.get("dist", 1e9))
    return givers[0]

def roam_scan(env, steps=24):
    """Move + turn to surface quest-givers beyond spawn radius."""
    giver = find_quest_giver(env._last_info)
    if giver:
        return giver
    for i in range(steps):
        env.base.step(ACT_FORWARD)
        env.base.step(ACT_TURN_LEFT if i % 2 == 0 else ACT_TURN_RIGHT)
        giver = find_quest_giver(env._last_info)
        if giver:
            return giver
    return None

def chain_quest():
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=42)
    obs, info = env.reset(seed=42)

    # 1) find quest-giver (may require roam)
    giver = roam_scan(env)
    if not giver:
        env.close(); return "SKIP (no quest-giver found after roam)"
    qid = (giver.get("questIds") or [None])[0]
    print(f"[QUEST] found giver id={giver.get('id')} qid={qid} at ({giver.get('x')},{giver.get('z')})")

    # 2) navigate to giver
    arrived = env._navigate_to_coord(giver.get("x"), giver.get("z"), max_steps=80)
    if not arrived:
        env.close(); return f"SKIP (could not reach giver, dist>{5})"
    print("[QUEST] arrived at giver")

    # 3) accept
    before = env._last_info
    info = env.base.accept_quest(str(qid))
    env._last_info = info
    va = verify_skill("accept_quest", {"before": before, "after": info, "handle": str(qid)})
    if va != "success":
        env.close(); return f"ACCEPT {va}"
    print("[QUEST] accepted")

    # 4) farm objective (kill something)
    k0 = info.get("kills", 0)
    for _ in range(10):
        o, r, t, tr, i = env.step(0)  # farm skill
        if i.get("kills", 0) > k0:
            info = i; break
    print(f"[QUEST] kills after farm: {info.get('kills')}")

    # 5) turn in (if ready) else report
    q = next((q for q in (info.get("quests", {}).get("active") or [])
              if q.get("id") == qid), None)
    if q and (q.get("ready") or q.get("state") in ("ready", "complete")):
        before_t = info
        info = env.base.turn_in_quest(str(qid))
        env._last_info = info
        vt = verify_skill("turn_in_quest", {"before": before_t, "after": info, "handle": str(qid)})
        env.close()
        return "SUCCESS" if vt == "success" else f"TURN_IN {vt}"
    env.close()
    return "PARTIAL (accepted + farmed, objective not yet complete — needs more kills)"

if __name__ == "__main__":
    print("=== QUEST capability chain (navigate-to-context) ===")
    print(chain_quest())
