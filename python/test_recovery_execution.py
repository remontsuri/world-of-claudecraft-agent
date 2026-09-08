"""Update test_recovery_execution.py for Phase 5 architecture.

Phase 5: before_action() no longer executes pending_recovery.
ArbitrationLayer.decide() handles recovery execution.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from autonomy import AutonomyLoop
from recovery import (ObjectiveBlacklist, RECOVERY_LADDER, DEFAULT_LADDER,
                      assert_recovery_executable, plan_recovery)


# ------------------------------------------------- каждая ветка исполнима

def test_every_recovery_action_has_an_implementation():
    """Ни одна стратегия не должна быть «только записью в лог»."""
    actions = assert_recovery_executable()
    assert len(actions) >= 25


def test_recovery_maps_to_skill():
    p = plan_recovery("buy_tool")
    assert p["kind"] == "skill" and p["skill"] == "buy"


def test_recovery_maps_to_navigation():
    p = plan_recovery("navigate_to_giver")
    assert p["kind"] == "navigate" and p["target"] == "quest_giver"


def test_recovery_maps_to_control():
    assert plan_recovery("abandon_objective") == {
        "kind": "control", "op": "abandon", "action": "abandon_objective"}


def test_unknown_recovery_never_returns_nothing():
    """Неизвестная стратегия -> replan, а не молчаливое None."""
    p = plan_recovery("no_such_strategy")
    assert p["kind"] == "control" and p["op"] == "replan"


def test_every_ladder_entry_is_mapped():
    known = set(DEFAULT_LADDER)
    for ladder in RECOVERY_LADDER.values():
        known.update(ladder)
    # Каждая стратегия имеет исполнение в recovery.py
    from recovery import RECOVERY_SKILL, RECOVERY_NAV, RECOVERY_CONTROL
    for a in known:
        assert a in RECOVERY_SKILL or a in RECOVERY_NAV or a in RECOVERY_CONTROL, \
            f"recovery action {a!r} has no implementation"


# ------------------------------------------------- отказ от цели

def test_blacklist_blocks_objective():
    """ObjectiveBlacklist блокирует цель на cooldown."""
    bl = ObjectiveBlacklist(cooldown_steps=60)
    bl.abandon("q1:kill:wolf", "no_mob")
    assert bl.is_blocked("q1:kill:wolf")
    assert bl.is_blocked("q1:kill:wolf", "no_mob")


def test_blacklist_expires_after_cooldown():
    """ObjectiveBlacklist снимает блокировку после cooldown."""
    bl = ObjectiveBlacklist(cooldown_steps=5)
    bl.abandon("q1:kill:wolf", "no_mob")
    assert bl.is_blocked("q1:kill:wolf")
    for _ in range(6):
        bl.tick()
    assert not bl.is_blocked("q1:kill:wolf")


def test_blacklist_does_not_block_none():
    """ObjectiveBlacklist не блокирует None."""
    bl = ObjectiveBlacklist(cooldown_steps=60)
    assert not bl.is_blocked(None)


# ------------------------------------------------- исполнение recovery (Phase 5)

def _info(giver_dist=40.0, mobs=0, hp=100):
    import tempfile
    return {
        "player": {"hp": hp, "maxHp": 100, "level": 1, "dead": False,
                   "pos": {"x": 0.0, "z": 0.0}},
        "player_pos": [0.0, 0.0],
        "player_class": "warrior",
        "nearby": [{"kind": "mob", "hp": 10, "level": 1, "dist": 6.0, "x": 5.0, "z": 0.0}] if mobs else [],
        "quests": {"active": [], "done": []},
        "inventory": [],
        "copper": 0, "kills": 0, "deaths": 0, "xp": 0,
    }


def _ws(info):
    ws = dict(info)
    ws["hp_frac"] = (info["player"]["hp"] or 0) / 100.0
    ws["bag_capacity"] = 16
    return ws


def test_failure_creates_pending_recovery():
    """Phase 5: after_action sets pending_recovery on failure."""
    loop = AutonomyLoop(min_dwell=1)
    info = _info(giver_dist=40.0)

    loop.before_action(info, _ws(info), ["accept_quest", "farm", "explore"])
    loop.after_action("accept_quest", info, _ws(info))

    assert loop.pending_recovery is not None, "recovery должен быть запланирован"


def test_arbitration_layer_executes_pending_recovery():
    """Phase 5: ArbitrationLayer executes pending_recovery."""
    from arbitration import ArbitrationLayer
    from goal_fsm import GoalFSM

    loop = AutonomyLoop(min_dwell=1)
    info = _info(giver_dist=40.0)

    # First step: failure creates pending_recovery
    loop.before_action(info, _ws(info), ["accept_quest", "farm", "explore"])
    loop.after_action("accept_quest", info, _ws(info))
    assert loop.pending_recovery is not None

    # Second step: ArbitrationLayer executes recovery
    fsm = GoalFSM()
    arb = ArbitrationLayer(
        fsm=fsm,
        planner=loop.planner,
        recovery_tracker=loop.recovery,
        loop_guard=loop.guard,
        blacklist=loop.blacklist,
        autonomy=loop,
    )
    from policy import GoalManager
    from memory import ExperienceStore
    policy = GoalManager(ExperienceStore(), temperature=1.2, seed=42)
    policy.world_mem = None

    action, ctx, reason = arb.decide(info, _ws(info), policy)
    assert reason == "recovery", f"expected recovery, got {reason}"
    assert loop.pending_recovery is None, "исполненный recovery не должен залипать"


def test_abandon_marks_objective_and_forces_replan():
    loop = AutonomyLoop(min_dwell=20)
    info = _info(mobs=1)
    obs = loop.before_action(info, _ws(info), ["farm"])["obs"]

    key = loop._objective_key(obs)
    loop.blacklist.abandon(key or "x:kill:y", "no_mob")
    loop.planner.force_replan()
    assert loop.planner.current is None, "force_replan должен снять удержание цели"


def test_success_clears_pending_recovery():
    loop = AutonomyLoop(min_dwell=1)
    info = _info(mobs=1)
    loop.before_action(info, _ws(info), ["farm"])
    loop.pending_recovery = {"kind": "skill", "skill": "farm"}

    after = _info(mobs=1)
    after["kills"] = 1
    loop.after_action("farm", after, _ws(after))
    assert loop.pending_recovery is None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
