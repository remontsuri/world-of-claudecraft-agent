import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from goal_fsm import GoalFSM, QuestState, MIN_DWELL_STEPS


def test_return_goal_survives_active_when_ready_exists():
    f = GoalFSM(memory_path=os.path.join(os.path.dirname(__file__), "_t_fsm.json"))
    f.set("RETURN_TO_GIVER", "q_prof_workorder_kitchens", step=MIN_DWELL_STEPS)
    ws = {"quest_status": "ACTIVE", "quest": {"id": "q_greyjaw", "phase": "ACTIVE",
                    "progress": 0, "required": 1}, "has_ready": True}
    f.update_from_world(ws)
    assert f.state == QuestState.RETURN_TO_GIVER, f"demoted to {f.state}"


def test_return_demotes_when_nothing_ready():
    f = GoalFSM(memory_path=os.path.join(os.path.dirname(__file__), "_t_fsm.json"))
    f.set("RETURN_TO_GIVER", "q_x", step=MIN_DWELL_STEPS)
    ws = {"quest_status": "ACTIVE", "quest": {"id": "q_greyjaw", "phase": "ACTIVE",
                    "progress": 0, "required": 1}, "has_ready": False}
    f.update_from_world(ws)
    assert f.state == QuestState.DO_OBJECTIVE
