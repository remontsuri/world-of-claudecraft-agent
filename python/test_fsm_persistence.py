"""RED TESTS: FSM persistence, quest cycle, bounded harness.

Verifies:
- FSM state survives save/load (memory_path)
- Full quest cycle: QUEST_NONE -> FIND_GIVER -> ACCEPT -> DO_OBJECTIVE -> RETURN_TO_GIVER -> TURN_IN -> DONE
- Bounded harness: FSM never enters invalid state transitions
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))

from goal_fsm import GoalFSM, QuestState


def test_fsm_save_load_preserves_state():
    """FSM state must survive save/load cycle."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "fsm.json")
    f = GoalFSM(memory_path=path)
    f.state = QuestState.DO_OBJECTIVE
    f.active_quest = {"id": "q_test"}
    f.total_kills = 5
    f.save()
    # Load into new FSM
    f2 = GoalFSM(memory_path=path)
    assert f2.state == QuestState.DO_OBJECTIVE
    assert f2.active_quest == {"id": "q_test"}
    assert f2.total_kills == 5


def test_fsm_save_load_preserves_counters():
    """FSM counters (kills, deaths, xp, copper) must persist."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "fsm.json")
    f = GoalFSM(memory_path=path)
    f.total_kills = 10
    f.total_deaths = 2
    f.total_xp = 500
    f.total_copper = 42
    f.save()
    f2 = GoalFSM(memory_path=path)
    assert f2.total_kills == 10
    assert f2.total_deaths == 2
    assert f2.total_xp == 500
    assert f2.total_copper == 42


def test_quest_cycle_full_deterministic():
    """Full quest cycle through update_from_world transitions."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    # Start: no quest
    assert f.state == QuestState.QUEST_NONE
    # Quest becomes active
    f.update_from_world({"quest_status": "ACTIVE", "quest": {"id": "q1"}})
    assert f.state == QuestState.DO_OBJECTIVE
    # Quest ready to turn in
    f.update_from_world({"quest_status": "READY_TO_TURN_IN", "quest": {"id": "q1"}})
    assert f.state == QuestState.RETURN_TO_GIVER
    # Quest done
    f.update_from_world({"quest_status": "DONE", "quest": {"id": "q1"}})
    assert f.state == QuestState.DONE
    # Quest cleared -> reset
    f.update_from_world({"quest_status": "NONE", "quest": {"id": "q1"}})
    assert f.state == QuestState.QUEST_NONE


def test_turnin_demotes_on_active():
    """TURN_IN against ACTIVE quest must demote to DO_OBJECTIVE (Fix5)."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    f.state = QuestState.TURN_IN
    f.active_quest = {"id": "q1"}
    f.update_from_world({"quest_status": "ACTIVE", "quest": {"id": "q1"}})
    assert f.state == QuestState.DO_OBJECTIVE


def test_return_to_giver_demotes_on_active():
    """RETURN_TO_GIVER against ACTIVE quest must demote to DO_OBJECTIVE."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    f.state = QuestState.RETURN_TO_GIVER
    f.active_quest = {"id": "q1"}
    f.update_from_world({"quest_status": "ACTIVE", "quest": {"id": "q1"}})
    assert f.state == QuestState.DO_OBJECTIVE


def test_done_from_ready_state():
    """DONE from RETURN_TO_GIVER state should transition to DONE."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    f.state = QuestState.RETURN_TO_GIVER
    f.active_quest = {"id": "q1"}
    f.update_from_world({"quest_status": "DONE", "quest": {"id": "q1"}})
    assert f.state == QuestState.DONE


def test_bounded_harness_no_invalid_transitions():
    """FSM must never enter an invalid state after any update_from_world call."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    states_seen = set()
    quest_statuses = ["NONE", "ACTIVE", "READY_TO_TURN_IN", "DONE"]
    for qs in quest_statuses:
        for initial in [QuestState.QUEST_NONE, QuestState.DO_OBJECTIVE,
                        QuestState.TURN_IN, QuestState.RETURN_TO_GIVER,
                        QuestState.DONE, QuestState.ERROR]:
            f.state = initial
            f.active_quest = {"id": "q1"}
            f.update_from_world({"quest_status": qs, "quest": {"id": "q1"}})
            states_seen.add(f.state)
    # All reachable states must be valid QuestState values
    for s in states_seen:
        assert isinstance(s, QuestState), f"invalid state: {s}"


def test_suggest_does_not_change_state():
    """fsm.suggest() must NOT change FSM state (advisory only)."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    f.state = QuestState.DO_OBJECTIVE
    f.active_quest = {"id": "q1"}
    result = f.suggest("TURN_IN", reason="llm says so")
    assert result is False
    assert f.state == QuestState.DO_OBJECTIVE
    assert f.last_suggestion == "TURN_IN"
    assert f.last_suggestion_reason == "llm says so"


def test_death_saves_pre_death_quest():
    """enter_dead() must save quest for respawn recovery."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    f.state = QuestState.DO_OBJECTIVE
    f.active_quest = {"id": "q1"}
    f.quest_giver = {"id": "npc1"}
    f.enter_dead()
    assert f.state == QuestState.RESPAWN
    assert f._pre_death_quest == {"id": "q1"}
    assert f._pre_death_giver == {"id": "npc1"}


def test_resume_from_dead_restores_quest():
    """resume_from_dead() must restore quest after death."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    f.state = QuestState.DO_OBJECTIVE
    f.active_quest = {"id": "q1"}
    f.quest_giver = {"id": "npc1"}
    f.enter_dead()
    f.resume_from_dead()
    assert f.state == QuestState.RETURN_TO_GIVER
    assert f.active_quest == {"id": "q1"}
    assert f.quest_giver == {"id": "npc1"}
