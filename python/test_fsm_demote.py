"""test_fsm_demote.py — Verify GoalFSM is demoted to a pure state tracker.

Acceptance criteria for STREAM J Phase 2:
- FSM has NO decide() method
- FSM has NO _handle_* methods
- FSM HAS phase property
- FSM only tracks state, doesn't decide actions
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from goal_fsm import GoalFSM, QuestState


def _fsm(tmpdir=None):
    d = tmpdir or tempfile.mkdtemp()
    return GoalFSM(memory_path=os.path.join(d, "fsm.json"))


class TestFSMNoDecide:
    """FSM must NOT have decide() or _handle_* methods."""

    def test_no_decide_method(self):
        f = _fsm()
        assert not hasattr(f, 'decide'), "FSM should not have decide() method"

    def test_no_handle_methods(self):
        f = _fsm()
        handle_methods = [
            '_handle_quest_none', '_handle_find_giver', '_handle_accept',
            '_handle_verify_accept', '_handle_do_objective',
            '_handle_verify_progress', '_handle_return_to_giver',
            '_handle_turn_in', '_handle_verify_turn_in', '_handle_done',
            '_handle_respawn', '_handle_stuck',
        ]
        for method_name in handle_methods:
            assert not hasattr(f, method_name), \
                f"FSM should not have {method_name}()"


class TestFSMHasPhaseProperty:
    """FSM must have a phase property returning the state name."""

    def test_phase_property_exists(self):
        f = _fsm()
        assert hasattr(f, 'phase'), "FSM should have phase property"

    def test_phase_quest_none(self):
        f = _fsm()
        assert f.phase == "QUEST_NONE"

    def test_phase_do_objective(self):
        f = _fsm()
        f.state = QuestState.DO_OBJECTIVE
        assert f.phase == "DO_OBJECTIVE"

    def test_phase_return_to_giver(self):
        f = _fsm()
        f.state = QuestState.RETURN_TO_GIVER
        assert f.phase == "RETURN_TO_GIVER"

    def test_phase_done(self):
        f = _fsm()
        f.state = QuestState.DONE
        assert f.phase == "DONE"

    def test_phase_turn_in(self):
        f = _fsm()
        f.state = QuestState.TURN_IN
        assert f.phase == "TURN_IN"

    def test_phase_find_giver(self):
        f = _fsm()
        f.state = QuestState.FIND_GIVER
        assert f.phase == "FIND_GIVER"


class TestFSMStateTracking:
    """FSM tracks state via update_from_world() — the ONLY method that matters."""

    def test_update_from_world_syncs_state(self):
        f = _fsm()
        ws = {"quest_status": "ACTIVE", "has_ready": False}
        f.update_from_world(ws)
        assert f.state == QuestState.DO_OBJECTIVE

    def test_update_from_world_resets_on_none(self):
        f = _fsm()
        f.state = QuestState.DONE
        ws = {"quest_status": "NONE", "has_ready": False}
        f.update_from_world(ws)
        assert f.state == QuestState.QUEST_NONE

    def test_update_from_world_turn_in_on_ready(self):
        f = _fsm()
        f.state = QuestState.DO_OBJECTIVE
        ws = {"quest_status": "READY_TO_TURN_IN", "has_ready": True}
        f.update_from_world(ws)
        assert f.state == QuestState.RETURN_TO_GIVER


class TestFSMKeptMethods:
    """FSM still has state-tracking methods."""

    def test_has_update_from_world(self):
        f = _fsm()
        assert hasattr(f, 'update_from_world')

    def test_has_reset(self):
        f = _fsm()
        assert hasattr(f, 'reset')

    def test_has_enter_dead(self):
        f = _fsm()
        assert hasattr(f, 'enter_dead')

    def test_has_resume_from_dead(self):
        f = _fsm()
        assert hasattr(f, 'resume_from_dead')

    def test_has_goal_property(self):
        f = _fsm()
        assert hasattr(f, 'goal')

    def test_has_set(self):
        f = _fsm()
        assert hasattr(f, 'set')

    def test_has_suggest(self):
        f = _fsm()
        assert hasattr(f, 'suggest')
