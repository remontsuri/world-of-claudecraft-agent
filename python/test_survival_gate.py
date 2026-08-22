"""TDD: survival gate — no walking skills at crit HP (run 20132 death loop)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from world_state import build_world_state
from policy import GoalManager
from memory import ExperienceStore


def _info(hp, max_hp=106):
    return {
        "player": {"hp": hp, "maxHp": max_hp, "dead": False},
        "player_pos": [0, 0], "nearby": [], "inventory": [],
        "quests": {
            "active": [{"id": "q_x", "state": "active",
                        "objectives": [{"current": 0, "required": 0}]}],
            "ready": [{"id": "q_boars", "state": "ready",
                       "objectives": [{"current": 5, "required": 5}],
                       "turnInNpc": {"x": -7.0, "z": 0.8}}],
            "done": [],
        },
        "kills": 0, "deaths": 0,
    }


def test_no_walk_skills_below_35pct_hp():
    info = _info(hp=20)   # ~19%
    ws = build_world_state(info)
    gm = GoalManager(ExperienceStore())
    for goal in ("DO_OBJECTIVE", "TURN_IN"):
        cands = gm._candidates(info, ws, goal=goal)
        assert "turn_in_quest" not in cands, (goal, cands)
        assert "return_to_giver" not in cands, (goal, cands)


def test_walk_skills_back_above_threshold():
    info = _info(hp=90)
    ws = build_world_state(info)
    gm = GoalManager(ExperienceStore())
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "turn_in_quest" in cands, cands
