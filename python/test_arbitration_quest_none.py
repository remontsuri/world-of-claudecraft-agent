"""test_arbitration_quest_none.py — RED test for farm→loot→heal loop fix.

Bug: Agent stuck in farm→loot→heal cycle when QUEST_NONE.
- dist=999.0 never changes (no quest accepted)
- kills stagnate (can't kill mobs)
- no quests accepted (agent farms instead of taking quest)

Root cause: arbitration.py has no logic to force accept_quest when
a quest giver is nearby in QUEST_NONE phase. The policy picks farm
because the `quest_givers` gate in policy.py is broken (ws has no
top-level `quest_givers` field).

Fix: arbitration.py detects QUEST_NONE + quest giver nearby and
forces accept_quest (or navigate if far).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from autonomy import AutonomyLoop
from goal_fsm import GoalFSM


def _info(hp=100, maxhp=100, dead=False, nearby=None, quests=None,
          copper=0, kills=0, deaths=0, inv=None, quest_states=None):
    return {
        "player": {"hp": hp, "maxHp": maxhp, "dead": dead},
        "player_pos": [0.0, 0.0],
        "player_class": "warrior",
        "nearby": nearby or [],
        "quests": quests or {"active": [], "done": []},
        "inventory": inv or [],
        "copper": copper, "kills": kills, "deaths": deaths, "xp": 0,
        "quest_states": quest_states or {},
    }


def _ws(info=None, **overrides):
    from world_state import build_world_state
    ws = build_world_state(info or _info())
    ws.update(overrides)
    return ws


def _make_arbitration_layer():
    """Create an ArbitrationLayer with a fresh AutonomyLoop."""
    from arbitration import ArbitrationLayer

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
    return arb, loop


def _make_policy():
    from policy import GoalManager
    from memory import ExperienceStore
    policy = GoalManager(ExperienceStore(), temperature=1.2, seed=42)
    policy.world_mem = None
    return policy


def test_quest_none_with_giver_nearby_forces_accept():
    """QUEST_NONE + quest giver nearby + available quest → accept_quest.

    This is the core bug: agent should take the quest, not farm.
    """
    arb, loop = _make_arbitration_layer()
    policy = _make_policy()

    # Quest giver nearby with an available quest
    nearby = [
        {
            "kind": "npc",
            "id": "marshal_redbrook",
            "name": "Marshal Redbrook",
            "x": 4.5,
            "z": 5.5,
            "dist": 5.0,
            "questIds": ["q_wolves"],
        },
        {
            "kind": "mob",
            "id": 152,
            "name": "forest_wolf",
            "x": 10.0,
            "z": 10.0,
            "dist": 14.0,
            "maxHp": 30,
            "hp": 30,
        },
    ]
    info = _info(nearby=nearby, quest_states={"q_wolves": "available"})
    ws = _ws(info)
    ws["quest_status"] = "NONE"
    ws["has_mob"] = True

    action, ctx, reason = arb.decide(info, ws, policy)

    # Agent should accept the quest, NOT farm
    assert action == "accept_quest", (
        f"Expected accept_quest, got {action} (reason={reason}). "
        f"Agent is stuck in farm→loot→heal loop!"
    )


def test_quest_none_with_giver_far_forces_navigate():
    """QUEST_NONE + quest giver far + available quest → navigate to giver.

    If the giver is out of interact range, agent should navigate first.
    """
    arb, loop = _make_arbitration_layer()
    policy = _make_policy()

    # Quest giver far away
    nearby = [
        {
            "kind": "npc",
            "id": "marshal_redbrook",
            "name": "Marshal Redbrook",
            "x": 50.0,
            "z": 50.0,
            "dist": 70.0,
            "questIds": ["q_wolves"],
        },
        {
            "kind": "mob",
            "id": 152,
            "name": "forest_wolf",
            "x": 10.0,
            "z": 10.0,
            "dist": 14.0,
            "maxHp": 30,
            "hp": 30,
        },
    ]
    info = _info(nearby=nearby, quest_states={"q_wolves": "available"})
    ws = _ws(info)
    ws["quest_status"] = "NONE"
    ws["has_mob"] = True

    action, ctx, reason = arb.decide(info, ws, policy)

    # Agent should navigate to the giver (or accept if close enough)
    assert action in ("accept_quest", "navigate", "explore"), (
        f"Expected accept_quest/navigate/explore, got {action} (reason={reason})"
    )


def test_quest_none_no_giver_farms():
    """QUEST_NONE + no quest giver nearby → policy decides (farm is OK).

    When there's no giver, farming is a valid choice.
    """
    arb, loop = _make_arbitration_layer()
    policy = _make_policy()

    # No quest giver, just a mob
    nearby = [
        {
            "kind": "mob",
            "id": 152,
            "name": "forest_wolf",
            "x": 10.0,
            "z": 10.0,
            "dist": 14.0,
            "maxHp": 30,
            "hp": 30,
        },
    ]
    info = _info(nearby=nearby)
    ws = _ws(info)
    ws["quest_status"] = "NONE"
    ws["has_mob"] = True

    action, ctx, reason = arb.decide(info, ws, policy)

    # Without a giver, farm is a valid choice (policy decides)
    assert action is not None


def test_quest_none_giver_with_done_quest_no_accept():
    """QUEST_NONE + giver nearby but all quests done → no accept_quest.

    If the only quest is already done, agent should NOT accept it.
    """
    arb, loop = _make_arbitration_layer()
    policy = _make_policy()

    # Quest giver nearby but quest already done
    nearby = [
        {
            "kind": "npc",
            "id": "marshal_redbrook",
            "name": "Marshal Redbrook",
            "x": 4.5,
            "z": 5.5,
            "dist": 5.0,
            "questIds": ["q_wolves"],
        },
    ]
    info = _info(
        nearby=nearby,
        quests={"active": [], "done": [{"id": "q_wolves"}]},
        quest_states={"q_wolves": "done"},
    )
    ws = _ws(info)
    ws["quest_status"] = "NONE"
    ws["has_mob"] = False

    action, ctx, reason = arb.decide(info, ws, policy)

    # Should NOT accept a done quest
    assert action != "accept_quest", (
        f"Should not accept done quest, got {action}"
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
