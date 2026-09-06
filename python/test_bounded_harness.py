"""BOUNDED HARNESS: FSM stress test — never crashes, never invalid state.

Runs all possible (initial_state, quest_status) combinations for N iterations
and verifies the FSM always ends in a valid QuestState.
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))

from goal_fsm import GoalFSM, QuestState


def test_bounded_harness_all_combinations():
    """Exhaustively test all (state, quest_status) combinations."""
    statuses = ["NONE", "ACTIVE", "READY_TO_TURN_IN", "DONE"]
    initial_states = list(QuestState)
    for initial in initial_states:
        for qs in statuses:
            f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
            f.state = initial
            f.active_quest = {"id": "q1"}
            f.update_from_world({"quest_status": qs, "quest": {"id": "q1"}})
            assert isinstance(f.state, QuestState), \
                f"({initial.name}, {qs}) -> {f.state} is not a QuestState"


def test_bounded_harness_random_walk():
    """Random walk through states — FSM must never crash."""
    import random
    random.seed(42)
    statuses = ["NONE", "ACTIVE", "READY_TO_TURN_IN", "DONE"]
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    for _ in range(100):
        qs = random.choice(statuses)
        f.update_from_world({"quest_status": qs, "quest": {"id": "q1"}})
        assert isinstance(f.state, QuestState)
        # State must always be valid
        assert f.state in list(QuestState)


def test_bounded_harness_never_crashes_on_decide():
    """FSM.decide() must never crash regardless of state."""
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "fsm.json"))
    ws = {"quest_status": "ACTIVE", "quest": {"id": "q1"},
          "hp_frac": 0.5, "has_mob": True, "distance_to_giver": 10.0}
    info = {"nearby": [], "player_pos": [0, 0]}
    for state in QuestState:
        f.state = state
        f.active_quest = {"id": "q1"}
        try:
            action, ctx = f.decide(ws, info)
        except Exception as e:
            raise AssertionError(f"decide() crashed in state {state.name}: {e}")
        assert isinstance(action, str), f"{state.name} -> {action} is not a string"
        assert isinstance(ctx, dict), f"{state.name} -> {ctx} is not a dict"


def test_bounded_harness_recovery_actions_valid():
    """All nav recovery actions must be valid skill names or None."""
    from navigation import NavigationController, STUCK, BLOCKED, TIMEOUT, NO_TARGET, ARRIVED, MOVING
    nav = NavigationController()
    for status in [STUCK, BLOCKED, TIMEOUT, NO_TARGET, ARRIVED, MOVING]:
        recovery = nav.recovery_for(status)
        if recovery is not None:
            assert isinstance(recovery, str), f"{status} recovery not a string: {recovery}"
