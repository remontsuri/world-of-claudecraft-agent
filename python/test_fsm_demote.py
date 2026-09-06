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

sys.path.insert(0, os.path.dirname(__file__))

from goal_fsm import GoalFSM, QuestState


def _fsm(tmpdir):
    f = GoalFSM(memory_path=os.path.join(tmpdir, "fsm.json"))
    f.set(QuestState.TURN_IN, "q_greyjaw")
    return f


def test_turnin_demotes_when_same_quest_active_incomplete(tmp_path=None):
    import tempfile
    f = _fsm(tempfile.mkdtemp())
    ws = {"quest": {"id": "q_greyjaw", "phase": "ACTIVE",
                    "progress": 0, "required": 1, "complete": False},
          "quest_status": "ACTIVE"}
    f.update_from_world(ws)
    assert f.state == QuestState.DO_OBJECTIVE, f"stale TURN_IN kept: {f.state}"
    assert f.goal == "DO_OBJECTIVE:q_greyjaw", f"goal mismatch: {f.goal}"


def test_turnin_kept_when_same_quest_ready():
    import tempfile
    f = _fsm(tempfile.mkdtemp())
    ws = {"quest": {"id": "q_greyjaw", "phase": "READY",
                    "progress": 1, "required": 1, "complete": True},
          "quest_status": "READY_TO_TURN_IN"}
    f.update_from_world(ws)
    # update_from_world transitions DO_OBJECTIVE -> RETURN_TO_GIVER,
    # not TURN_IN. TURN_IN only comes from RETURN_TO_GIVER + close proximity.
    # But READY_TO_TURN_IN + state=TURN_IN is NOT in the transition list —
    # TURN_IN is terminal until verify. The state machine stays TURN_IN
    # (demote only happens when ACTIVE incomplete is observed under TURN_IN
    # via update_from_world — and that test is above).
    # This test verifies READY does NOT force-demote back to DO_OBJECTIVE.
    assert f.state == QuestState.TURN_IN, f"state={f.state}"


def test_turnin_demotes_then_repromotes_via_update():
    """Full regression: TURN_IN -> (observe ACTIVE 0/1) -> DO_OBJECTIVE."""
    import tempfile
    f = _fsm(tempfile.mkdtemp())
    f.update_from_world({"quest_status": "ACTIVE"})
    assert f.state == QuestState.DO_OBJECTIVE
    # Now if quest becomes ready again
    f.update_from_world({"quest_status": "READY_TO_TURN_IN"})
    assert f.state == QuestState.RETURN_TO_GIVER
