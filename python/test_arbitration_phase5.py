"""Update test_arbitration_phase5.py for Phase 5 architecture."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from autonomy import AutonomyLoop
from goal_fsm import GoalFSM
from arbitration import ArbitrationLayer  # noqa: F401 — used by inline imports below


def _info(hp=100, maxhp=100, dead=False, nearby=None, quests=None,
          copper=0, kills=0, deaths=0, inv=None):
    return {
        "player": {"hp": hp, "maxHp": maxhp, "dead": dead},
        "player_pos": [0.0, 0.0],
        "player_class": "warrior",
        "nearby": nearby or [],
        "quests": quests or {"active": [], "done": []},
        "inventory": inv or [],
        "copper": copper, "kills": kills, "deaths": deaths, "xp": 0,
    }


def _ws(info=None, **overrides):
    from world_state import build_world_state
    ws = build_world_state(info or _info())
    ws.update(overrides)
    return ws


def test_before_action_returns_minimal_dict():
    """Phase 5: before_action is a thin wrapper."""
    loop = AutonomyLoop()
    info = _info()
    out = loop.before_action(info, _ws(info), ["farm", "buy"])
    assert "candidates" in out
    assert "subgoal" in out
    assert "signals" in out
    assert "obs" in out
    assert "advisor" in out
    assert out["signals"] is None


def test_before_action_does_not_mask_candidates():
    """Phase 5: before_action no longer masks candidates."""
    loop = AutonomyLoop()
    info = _info()
    out = loop.before_action(info, _ws(info), ["buy", "gather"])
    assert "buy" in out["candidates"]
    assert "gather" in out["candidates"]


def test_before_action_does_not_emit_signals():
    """Phase 5: before_action no longer emits signals."""
    loop = AutonomyLoop()
    loop.pending_recovery = {"kind": "skill", "skill": "heal", "action": "retreat_and_heal"}
    info = _info(hp=30, maxhp=100)
    out = loop.before_action(info, _ws(info), ["farm", "heal", "explore"])
    assert out["signals"] is None


def test_arbitration_layer_handles_recovery():
    """Phase 5: ArbitrationLayer handles pending_recovery."""
    from arbitration import ArbitrationLayer
    from goal_fsm import GoalFSM

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


def test_arbitration_layer_handles_loop():
    """Phase 5: ArbitrationLayer handles loop detection.
    
    When a loop is detected, the action is blocked by cooldown and
    policy decides among remaining candidates.
    """
    from arbitration import ArbitrationLayer
    from goal_fsm import GoalFSM

    loop = AutonomyLoop()
    # Trigger loop by repeating same action without progress
    for _ in range(25):
        loop.guard.observe("farm", False, state_key="cell_0_0")

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
    # Loop detected -> action blocked by cooldown -> policy decides
    # The key behavior: "farm" should be blocked by cooldown
    assert loop.guard.blocked("farm")
    # Policy decides among non-blocked candidates
    assert reason == "policy"


def test_arbitration_layer_safety_override():
    """Phase 5: Safety overrides policy."""
    from arbitration import ArbitrationLayer
    from goal_fsm import GoalFSM

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


def test_arbitration_layer_critical_hp_safety():
    """Phase 5: Critical HP triggers safety (heal)."""
    from arbitration import ArbitrationLayer
    from goal_fsm import GoalFSM

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
    # Critical HP with healing available
    info = _info(hp=10, maxhp=100, inv=[{"itemId": "potion", "count": 3}])
    ws = _ws(info)
    ws["hp_frac"] = 0.1  # Force critical HP
    from policy import GoalManager
    from memory import ExperienceStore
    policy = GoalManager(ExperienceStore(), temperature=1.2, seed=42)
    policy.world_mem = None

    action, ctx, reason = arb.decide(info, ws, policy)
    assert action == "heal"
    assert reason == "safety"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
