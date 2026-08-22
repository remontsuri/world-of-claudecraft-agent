"""Tests for the quest-phase truth + action-mask fix.

These run WITHOUT a live game tab. They assert the TWO invariants the user
required after observing the agent re-accepting an already-accepted quest
(NPC: "already taken" -> FAILURE) and a false READY_TO_TURN_IN on 0/0:

  1. world_state.build_world_state: a quest with EMPTY objectives (or 0/0
     progress) is phase ACTIVE / status ACTIVE, NEVER READY_TO_TURN_IN.
     Only a quest with objectives present AND every current >= required is
     READY (complete=True).

  2. policy.GoalManager._candidates: when the structured view says the quest
     is already accepted, accept_quest is NEVER a candidate (the Q-policy
     cannot learn "when ACTIVE, try accept_quest"). When complete, turn_in_quest
     IS a candidate. explore is suppressed while a quest is active/ready.

These prevent the replay from being poisoned with accept_quest/FAILURE lessons.
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(__file__))

from world_state import build_world_state
from policy import GoalManager
from memory import ExperienceStore


def _fake_info(quests_active):
    """Build a minimal env info dict with the given quests.active list."""
    return {
        "player": {"hp": 100, "maxHp": 100, "dead": False},
        "player_pos": [0, 0],
        "nearby": [],
        "inventory": [],
        "quests": {"active": quests_active, "ready": [], "done": []},
        "kills": 0, "deaths": 0,
    }


def test_empty_objectives_is_ACTIVE_not_READY():
    """A freshly-accepted quest (bridge reports 0/0, no objectives) must be ACTIVE."""
    info = _fake_info([{
        "id": "q_bones", "state": "active",
        "objectives": [],  # bridge hasn't reported objectives yet
    }])
    ws = build_world_state(info)
    assert ws["quest"]["phase"] == "ACTIVE", ws["quest"]
    assert ws["quest"]["status"] if "status" in ws["quest"] else ws["quest_status"] == "ACTIVE"
    assert ws["quest_status"] == "ACTIVE", "status must be ACTIVE, not READY_TO_TURN_IN"
    assert ws["quest"]["accepted"] is True
    assert ws["quest"]["complete"] is False


def test_zero_progress_with_objectives_is_ACTIVE():
    """objectives present but current<required -> ACTIVE (not READY)."""
    info = _fake_info([{
        "id": "q_bones", "state": "active",
        "objectives": [{"current": 0, "required": 5}],
    }])
    ws = build_world_state(info)
    assert ws["quest"]["phase"] == "ACTIVE"
    assert ws["quest_status"] == "ACTIVE"
    assert ws["quest"]["complete"] is False


def test_all_objectives_complete_is_READY():
    """every current>=required AND objectives present -> READY (complete=True)."""
    info = _fake_info([{
        "id": "q_bones", "state": "active",
        "objectives": [{"current": 5, "required": 5}],
    }])
    ws = build_world_state(info)
    assert ws["quest"]["phase"] == "READY"
    assert ws["quest_status"] == "READY_TO_TURN_IN"
    assert ws["quest"]["complete"] is True


def test_accepted_quest_masks_accept_action():
    """When the structured view says accepted, accept_quest is NOT a candidate."""
    # accepted quest, objective not done, a quest NPC nearby
    info = _fake_info([{
        "id": "q_bones", "state": "active",
        "objectives": [{"current": 0, "required": 5}],
    }])
    info["nearby"] = [
        {"id": 1, "kind": "npc", "name": "Aldric", "questIds": ["q_bones"], "x": 2, "z": 3},
        {"id": 99, "kind": "mob", "type": "mob", "name": "wolf", "x": 1, "z": 1, "maxHp": 20},
    ]
    ws = build_world_state(info)
    gm = GoalManager(ExperienceStore())
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "accept_quest" not in cands, "accepted quest must NOT offer accept_quest: %s" % cands
    # farm/loot should be offered for objective progress
    assert "farm" in cands, cands


def test_complete_quest_offers_turn_in_not_accept():
    """When complete, turn_in_quest is a candidate and accept_quest is not."""
    info = _fake_info([{
        "id": "q_bones", "state": "ready",
        "objectives": [{"current": 5, "required": 5}],
    }])
    info["nearby"] = [{"id": 1, "kind": "npc", "type": "npc", "name": "Aldric",
                        "questIds": ["q_bones"], "x": 2, "z": 3}]
    ws = build_world_state(info)
    gm = GoalManager(ExperienceStore())
    cands = gm._candidates(info, ws, goal="TURN_IN")
    assert "turn_in_quest" in cands, cands
    assert "accept_quest" not in cands, "complete quest must NOT offer accept_quest: %s" % cands


def test_explore_suppressed_while_quest_active():
    """explore must not appear while a quest is active (no drift to fences)."""
    info = _fake_info([{
        "id": "q_bones", "state": "active",
        "objectives": [{"current": 0, "required": 5}],
    }])
    ws = build_world_state(info)
    gm = GoalManager(ExperienceStore())
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "explore" not in cands, "explore must be suppressed while quest active: %s" % cands


if __name__ == "__main__":
    import unittest
    unittest.main()
