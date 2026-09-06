"""RED TESTS: quest cycle (accept -> objective -> turn-in -> next quest).

Verifies the quest resolution chain end-to-end through the FSM + world_state.
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))

from goal_fsm import GoalFSM, QuestState
from world_state import build_world_state


def test_quest_accept_transitions_to_do_objective():
    """When a quest is accepted (ACTIVE), FSM must be in DO_OBJECTIVE."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    assert f.state == QuestState.QUEST_NONE
    f.update_from_world({"quest_status": "ACTIVE", "quest": {"id": "q1"}})
    assert f.state == QuestState.DO_OBJECTIVE


def test_quest_ready_transitions_to_return():
    """When quest objectives complete (READY_TO_TURN_IN), FSM must return."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    f.state = QuestState.DO_OBJECTIVE
    f.active_quest = {"id": "q1"}
    f.update_from_world({"quest_status": "READY_TO_TURN_IN", "quest": {"id": "q1"}})
    assert f.state == QuestState.RETURN_TO_GIVER


def test_quest_done_transitions_to_done():
    """When quest is DONE, FSM must be in DONE."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    f.state = QuestState.RETURN_TO_GIVER
    f.active_quest = {"id": "q1"}
    f.update_from_world({"quest_status": "DONE", "quest": {"id": "q1"}})
    assert f.state == QuestState.DONE


def test_quest_none_resets_after_done():
    """When quest is cleared (NONE) after DONE, FSM must reset."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    f.state = QuestState.DONE
    f.active_quest = {"id": "q1"}
    f.update_from_world({"quest_status": "NONE", "quest": {"id": "q1"}})
    assert f.state == QuestState.QUEST_NONE
    assert f.active_quest is None


def test_quest_none_resets_after_error():
    """When quest is cleared (NONE) after ERROR, FSM must reset."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    f.state = QuestState.ERROR
    f.active_quest = {"id": "q1"}
    f.update_from_world({"quest_status": "NONE", "quest": {"id": "q1"}})
    assert f.state == QuestState.QUEST_NONE


def test_world_state_quest_status_active():
    """build_world_state must produce quest_status=ACTIVE for active quest."""
    info = {
        "quests": {
            "active": [{"id": "q1", "objectives": [{"current": 3, "required": 5}]}],
            "ready": [],
            "done": [],
        }
    }
    ws = build_world_state(info)
    assert ws["quest_status"] == "ACTIVE"


def test_world_state_quest_status_ready():
    """build_world_state must produce quest_status=READY_TO_TURN_IN for complete quest."""
    info = {
        "quests": {
            "active": [{"id": "q1", "objectives": [{"current": 5, "required": 5}]}],
            "ready": [],
            "done": [],
        }
    }
    ws = build_world_state(info)
    assert ws["quest_status"] == "READY_TO_TURN_IN"


def test_world_state_quest_status_none():
    """build_world_state must produce quest_status=NONE when no quests."""
    info = {"quests": {"active": [], "ready": [], "done": []}}
    ws = build_world_state(info)
    assert ws["quest_status"] == "NONE"


def test_full_quest_cycle_integration():
    """Full quest cycle: ACTIVE -> READY -> DONE -> NONE."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    # Quest accepted
    f.update_from_world({"quest_status": "ACTIVE", "quest": {"id": "q1"}})
    assert f.state == QuestState.DO_OBJECTIVE
    # Quest complete
    f.update_from_world({"quest_status": "READY_TO_TURN_IN", "quest": {"id": "q1"}})
    assert f.state == QuestState.RETURN_TO_GIVER
    # Quest turned in
    f.update_from_world({"quest_status": "DONE", "quest": {"id": "q1"}})
    assert f.state == QuestState.DONE
    # Quest cleared
    f.update_from_world({"quest_status": "NONE", "quest": {"id": "q1"}})
    assert f.state == QuestState.QUEST_NONE
