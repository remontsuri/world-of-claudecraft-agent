"""Fix5 regression: TURN_IN goal must demote when the SAME quest is observed
ACTIVE with incomplete objectives.

2026-08-23 live run: q_greyjaw (0/1) sat in the active list while the FSM held
goal=TURN_IN for the same id — R1 only handled a DIFFERENT tracked id, so the
phase gate built an empty candidate set, the full-list fallback fired, and the
agent farmed under a turn-in phase for 700+ steps. A TURN_IN goal against an
incomplete objective count is simply stale: demote to DO_OBJECTIVE.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from goal_fsm import GoalFSM, QuestState


def _fsm(tmpdir):
    f = GoalFSM(memory_path=os.path.join(tmpdir, "fsm.json"))
    f.state = QuestState.TURN_IN
    f.active_quest = {"id": "q_greyjaw"}
    return f


def test_turnin_demotes_when_same_quest_active_incomplete():
    f = _fsm(tempfile.mkdtemp())
    ws = {"quest_status": "ACTIVE",
          "quest": {"id": "q_greyjaw", "phase": "ACTIVE",
                    "progress": 0, "required": 1, "complete": False}}
    f.update_from_world(ws)
    assert f.state == QuestState.DO_OBJECTIVE, f"stale TURN_IN kept: {f.state}"


def test_turnin_kept_when_same_quest_ready():
    f = _fsm(tempfile.mkdtemp())
    ws = {"quest_status": "READY_TO_TURN_IN",
          "quest": {"id": "q_greyjaw", "phase": "READY",
                    "progress": 1, "required": 1, "complete": True}}
    f.update_from_world(ws)
    assert f.state == QuestState.TURN_IN
