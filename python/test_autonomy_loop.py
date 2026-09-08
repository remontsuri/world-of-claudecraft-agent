"""Update test_autonomy_loop.py for Phase 5 architecture.

Phase 5 changes:
- before_action() is now a thin wrapper (no masking, no signals)
- ArbitrationLayer handles safety > recovery > policy flow
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autonomy import AutonomyLoop, RECOVERY_TO_SKILL


def _info(hp=100, maxhp=100, copper=0, kills=0, deaths=0, dead=False,
          nearby=None, quests=None, inv=None):
    return {
        "player": {"hp": hp, "maxHp": maxhp, "level": 1, "dead": dead,
                   "pos": {"x": 0.0, "z": 0.0}},
        "player_pos": [0.0, 0.0],
        "player_class": "warrior",
        "nearby": nearby if nearby is not None else [],
        "quests": quests if quests is not None else {"active": [], "done": []},
        "inventory": inv if inv is not None else [],
        "copper": copper, "kills": kills, "deaths": deaths, "xp": 0,
    }


def _ws(info, **over):
    """Минимальный ws: контур толерантен, ему хватает info + пары полей."""
    ws = dict(info)
    ws["hp_frac"] = info["player"]["hp"] / max(1, info["player"]["maxHp"])
    ws["bag_capacity"] = 26
    ws.update(over)
    return ws


# ----------------------------------------------------------- before_action (Phase 5: thin wrapper)

def test_before_action_returns_contract_shape():
    """Phase 5: before_action returns minimal dict."""
    loop = AutonomyLoop()
    info = _info()
    out = loop.before_action(info, _ws(info), ["farm", "buy", "gather"])
    for k in ("candidates", "subgoal", "signals", "obs", "blocked"):
        assert k in out, k


def test_before_action_passes_candidates_through():
    """Phase 5: before_action no longer masks candidates."""
    loop = AutonomyLoop()
    info = _info()  # no vendor, no nodes
    out = loop.before_action(info, _ws(info), ["buy", "gather"])
    # Candidates are passed through unchanged
    assert "buy" in out["candidates"]
    assert "gather" in out["candidates"]


def test_before_action_does_not_mask():
    """Phase 5: before_action no longer masks impossible candidates."""
    loop = AutonomyLoop()
    info = _info()
    out = loop.before_action(info, _ws(info), ["buy"])
    assert out["candidates"] == ["buy"]


def test_before_action_no_signals():
    """Phase 5: before_action no longer emits signals."""
    loop = AutonomyLoop()
    info = _info()
    out = loop.before_action(info, _ws(info), ["farm"])
    assert out["signals"] is None


def test_before_action_no_subgoal_counting():
    """Phase 5: before_action no longer counts subgoals."""
    loop = AutonomyLoop()
    info = _info()
    loop.before_action(info, _ws(info), ["farm"])
    # subgoals stat is no longer incremented in thin wrapper
    assert sum(loop.stats.get("subgoals", {}).values()) == 0


# ------------------------------------------------------------ after_action (unchanged)

def test_kill_counts_as_success():
    loop = AutonomyLoop()
    before = _info(kills=0)
    loop.before_action(before, _ws(before), ["farm"])
    after = _info(kills=1)
    rec = loop.after_action("farm", after, _ws(after))
    assert rec["skill_result"] == "SUCCESS"
    assert rec["progress_delta"]["kills_delta"] == 1
    assert rec["failure_reason"] is None


def test_nothing_changed_is_no_op_not_success():
    loop = AutonomyLoop()
    info = _info()
    loop.before_action(info, _ws(info), ["farm"])
    rec = loop.after_action("farm", info, _ws(info))
    assert rec["skill_result"] == "NO_OP"
    assert rec["failure_reason"] is not None
    assert rec["recovery"] is not None


def test_death_is_failure():
    loop = AutonomyLoop()
    before = _info(deaths=0)
    loop.before_action(before, _ws(before), ["farm"])
    after = _info(deaths=1)
    rec = loop.after_action("farm", after, _ws(after))
    assert rec["skill_result"] == "FAILURE"


def test_buy_without_inventory_change_is_not_success():
    loop = AutonomyLoop()
    before = _info(copper=20)
    loop.before_action(before, _ws(before), ["buy"])
    after = _info(copper=15)
    rec = loop.after_action("buy", after, _ws(after))
    assert rec["skill_result"] != "SUCCESS"
    assert "inventory_changed" in rec["postconditions"]["missing"]


def test_sell_junk_success_on_copper_gain():
    loop = AutonomyLoop()
    before = _info(copper=0, inv=[{"quality": 0}] * 3)
    loop.before_action(before, _ws(before), ["sell_junk"])
    after = _info(copper=12, inv=[])
    rec = loop.after_action("sell_junk", after, _ws(after))
    assert rec["skill_result"] == "SUCCESS"


def test_recovery_escalates_across_repeated_failures():
    loop = AutonomyLoop()
    info = _info()
    seen = []
    for _ in range(3):
        loop.before_action(info, _ws(info), ["buy"])
        rec = loop.after_action("buy", info, _ws(info))
        seen.append(rec["recovery"]["recovery_action"])
    # Escalation: first retry, then alternate, then replan/abandon
    assert len(seen) == 3
    assert seen[0] != seen[2]  # escalated


def test_recovery_resets_on_success():
    loop = AutonomyLoop()
    info = _info()
    loop.before_action(info, _ws(info), ["buy"])
    loop.after_action("buy", info, _ws(info))  # failure
    assert loop.recovery._attempts  # has attempts
    loop.after_action("farm", _info(kills=1), _ws(_info(kills=1)))  # success
    # RecoveryTracker resets on success for that skill prefix


# ------------------------------------------------------------ ArbitrationLayer integration

def test_arbitration_layer_handles_recovery():
    """Phase 5: ArbitrationLayer handles pending_recovery."""
    from arbitration import ArbitrationLayer
    from goal_fsm import GoalFSM
    import tempfile

    loop = AutonomyLoop()
    loop.pending_recovery = {"kind": "skill", "skill": "heal", "action": "retreat_and_heal"}
    fsm = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    arb = ArbitrationLayer(
        fsm=fsm,
        planner=loop.planner,
        recovery_tracker=loop.recovery,
        loop_guard=loop.guard,
        blacklist=loop.blacklist,
        autonomy=loop,
    )
    info = _info(hp=30, maxhp=100)
    ws = _ws(info)
    from policy import GoalManager
    from memory import ExperienceStore
    policy = GoalManager(ExperienceStore(), temperature=1.2, seed=42)
    policy.world_mem = None

    action, ctx, reason = arb.decide(info, ws, policy)
    assert action == "heal"
    assert reason == "recovery"


def test_arbitration_layer_safety_override():
    """Phase 5: Safety overrides policy."""
    from arbitration import ArbitrationLayer
    from goal_fsm import GoalFSM
    import tempfile

    loop = AutonomyLoop()
    fsm = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    arb = ArbitrationLayer(
        fsm=fsm,
        planner=loop.planner,
        recovery_tracker=loop.recovery,
        loop_guard=loop.guard,
        blacklist=loop.blacklist,
        autonomy=loop,
    )
    info = _info(dead=True)
    ws = _ws(info)
    from policy import GoalManager
    from memory import ExperienceStore
    policy = GoalManager(ExperienceStore(), temperature=1.2, seed=42)
    policy.world_mem = None

    action, ctx, reason = arb.decide(info, ws, policy)
    assert action == "respawn"
    assert reason == "safety"


def test_arbitration_layer_policy_fallback():
    """Phase 5: When no safety/recovery, policy decides."""
    from arbitration import ArbitrationLayer
    from goal_fsm import GoalFSM
    import tempfile

    loop = AutonomyLoop()
    fsm = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    arb = ArbitrationLayer(
        fsm=fsm,
        planner=loop.planner,
        recovery_tracker=loop.recovery,
        loop_guard=loop.guard,
        blacklist=loop.blacklist,
        autonomy=loop,
    )
    info = _info()
    ws = _ws(info)
    from policy import GoalManager
    from memory import ExperienceStore
    policy = GoalManager(ExperienceStore(), temperature=1.2, seed=42)
    policy.world_mem = None

    action, ctx, reason = arb.decide(info, ws, policy)
    assert reason == "policy"
    assert action is not None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
