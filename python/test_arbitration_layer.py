"""test_arbitration_layer.py — Tests for the ArbitrationLayer.

Verifies that decision logic is correctly separated from FSM state tracking.
The ArbitrationLayer decides WHAT to do; the FSM tracks WHAT STATE we're in.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from goal_fsm import GoalFSM, QuestState, INTERACT_RANGE
from arbitration_layer import ArbitrationLayer


def _giver(x, z, d=None, qids=None):
    return {
        "kind": "npc",
        "questIds": qids or ["q1"],
        "x": x, "z": z,
        "_dist": d if d is not None else (x ** 2 + z ** 2) ** 0.5,
    }


def _fsm(tmpdir=None):
    d = tmpdir or tempfile.mkdtemp()
    return GoalFSM(memory_path=os.path.join(d, "fsm.json"))


class TestArbitrationLayerSeparation:
    """ArbitrationLayer modifies FSM state but doesn't own it."""

    def test_arbitration_layer_is_separate_from_fsm(self):
        """ArbitrationLayer and FSM are separate classes."""
        f = _fsm()
        arb = ArbitrationLayer()
        assert f is not arb
        assert hasattr(arb, 'decide')
        assert not hasattr(f, 'decide')  # FSM no longer has decide()

    def test_fsm_has_no_decide_method(self):
        """FSM must NOT have decide() — that's ArbitrationLayer's job."""
        f = _fsm()
        assert not hasattr(f, 'decide'), "FSM should not have decide() method"

    def test_fsm_has_no_handle_methods(self):
        """FSM must NOT have _handle_* methods — those are in ArbitrationLayer."""
        f = _fsm()
        for method_name in ['_handle_quest_none', '_handle_find_giver',
                           '_handle_accept', '_handle_do_objective',
                           '_handle_return_to_giver', '_handle_turn_in']:
            assert not hasattr(f, method_name), \
                f"FSM should not have {method_name}() — it's in ArbitrationLayer"


class TestArbitrationLayerDecisions:
    """ArbitrationLayer makes correct decisions for each FSM state."""

    def test_quest_none_with_no_nearby_explores(self):
        f = _fsm()
        arb = ArbitrationLayer()
        action, ctx = arb.decide(f, {}, {"nearby": []})
        assert action == "explore"
        assert ctx["reason"] == "no_available_quest_giver"

    def test_quest_none_with_giver_navigates(self):
        f = _fsm()
        arb = ArbitrationLayer()
        action, ctx = arb.decide(f, {}, {"nearby": [_giver(20, 0)]})
        assert f.state == QuestState.FIND_GIVER
        assert action == "navigate"

    def test_find_giver_close_enough_accepts(self):
        f = _fsm()
        f.state = QuestState.FIND_GIVER
        f.quest_giver = {"x": 3, "z": 0, "dist": 3.0}
        arb = ArbitrationLayer()
        action, ctx = arb.decide(f, {}, {"player_pos": [0, 0]})
        assert f.state == QuestState.ACCEPT
        assert action == "accept_quest"

    def test_accept_transitions_to_verify(self):
        f = _fsm()
        f.state = QuestState.ACCEPT
        f.quest_giver = {"x": 0, "z": 0}
        arb = ArbitrationLayer()
        action, ctx = arb.decide(f, {}, {})
        assert f.state == QuestState.VERIFY_ACCEPT
        assert action == "accept_quest"

    def test_verify_accept_to_do_objective(self):
        f = _fsm()
        f.state = QuestState.VERIFY_ACCEPT
        f.quest_giver = {"x": 0, "z": 0}
        arb = ArbitrationLayer()
        action, ctx = arb.decide(f, {"quest_status": "ACTIVE"}, {})
        assert f.state == QuestState.DO_OBJECTIVE

    def test_do_objective_farms_when_mob_present(self):
        f = _fsm()
        f.state = QuestState.DO_OBJECTIVE
        arb = ArbitrationLayer()
        action, ctx = arb.decide(f, {"quest_status": "ACTIVE", "has_mob": True,
                                      "quest_struct": {"objectives": [{"type": "kill"}]},
                                      "quest_system_ready": True}, {})
        assert action == "farm"

    def test_do_objective_explores_when_no_mob(self):
        f = _fsm()
        f.state = QuestState.DO_OBJECTIVE
        arb = ArbitrationLayer()
        action, ctx = arb.decide(f, {"quest_status": "ACTIVE", "has_mob": False}, {})
        assert action == "explore"

    def test_ready_to_turn_in_transitions_to_return(self):
        f = _fsm()
        f.state = QuestState.DO_OBJECTIVE
        f.quest_giver = {"x": 50, "z": 0}
        arb = ArbitrationLayer()
        action, ctx = arb.decide(f, {"quest_status": "READY_TO_TURN_IN"}, {"player_pos": [0, 0]})
        assert f.state == QuestState.RETURN_TO_GIVER
        assert action == "navigate"

    def test_return_to_giver_arrives_then_turn_in(self):
        f = _fsm()
        f.state = QuestState.RETURN_TO_GIVER
        f.quest_giver = {"x": 3, "z": 0}
        arb = ArbitrationLayer()
        action, ctx = arb.decide(f, {}, {"player_pos": [0, 0]})
        assert f.state == QuestState.TURN_IN
        assert action == "turn_in_quest"

    def test_turn_in_to_verify(self):
        f = _fsm()
        f.state = QuestState.TURN_IN
        f.quest_giver = {"x": 0, "z": 0}
        arb = ArbitrationLayer()
        action, ctx = arb.decide(f, {}, {})
        assert f.state == QuestState.VERIFY_TURN_IN
        assert action == "turn_in_quest"

    def test_verify_turn_in_to_done(self):
        f = _fsm()
        f.state = QuestState.VERIFY_TURN_IN
        f.quest_giver = {"x": 0, "z": 0}
        arb = ArbitrationLayer()
        action, ctx = arb.decide(f, {"quest_status": "DONE"}, {})
        assert f.state == QuestState.DONE

    def test_done_resets_to_none(self):
        f = _fsm()
        f.state = QuestState.DONE
        f.active_quest = {"id": "q1"}
        arb = ArbitrationLayer()
        action, ctx = arb.decide(f, {}, {})
        assert f.state == QuestState.QUEST_NONE
        assert f.active_quest is None

    def test_full_quest_cycle_integration(self):
        """Simulate a complete quest cycle through ArbitrationLayer + FSM."""
        f = _fsm()
        arb = ArbitrationLayer()
        # 1. Start: no quest
        assert f.state == QuestState.QUEST_NONE
        # 2. Find giver
        arb.decide(f, {}, {"nearby": [_giver(3, 0, qids=["q_bones"])]})
        assert f.state == QuestState.FIND_GIVER
        # 3. Approach giver
        f.quest_giver = {"x": 3, "z": 0, "dist": 3.0}
        arb.decide(f, {}, {"player_pos": [0, 0]})
        assert f.state == QuestState.ACCEPT
        # 4. Accept quest
        arb.decide(f, {}, {})
        assert f.state == QuestState.VERIFY_ACCEPT
        # 5. Quest becomes active
        arb.decide(f, {"quest_status": "ACTIVE"}, {})
        assert f.state == QuestState.DO_OBJECTIVE
        # 6. Farm mobs
        arb.decide(f, {"quest_status": "ACTIVE", "has_mob": True,
                       "quest_struct": {"objectives": [{"type": "kill"}]},
                       "quest_system_ready": True}, {})
        assert f.state == QuestState.DO_OBJECTIVE
        # 7. Quest ready to turn in
        f.quest_giver = {"x": 50, "z": 0}
        arb.decide(f, {"quest_status": "READY_TO_TURN_IN"}, {"player_pos": [0, 0]})
        assert f.state == QuestState.RETURN_TO_GIVER
        # 8. Arrive at giver
        f.quest_giver = {"x": 3, "z": 0}
        arb.decide(f, {}, {"player_pos": [0, 0]})
        assert f.state == QuestState.TURN_IN
        # 9. Turn in
        arb.decide(f, {}, {})
        assert f.state == QuestState.VERIFY_TURN_IN
        # 10. Quest done
        arb.decide(f, {"quest_status": "DONE"}, {})
        assert f.state == QuestState.DONE
        # 11. Reset
        arb.decide(f, {}, {})
        assert f.state == QuestState.QUEST_NONE


class TestArbitrationLayerDoesNotDuplicateSafety:
    """ArbitrationLayer does NOT contain HP override — that's SafetyLayer's job."""

    def test_arbitration_layer_has_no_hp_override(self):
        """ArbitrationLayer should NOT have HP-based safety logic."""
        arb = ArbitrationLayer()
        assert not hasattr(arb, 'CRITICAL_HP_FRAC')
        assert not hasattr(arb, 'check_hp')

    def test_arbitration_layer_ignores_hp_for_decision(self):
        """ArbitrationLayer does not force heal based on HP."""
        f = _fsm()
        f.state = QuestState.DO_OBJECTIVE
        arb = ArbitrationLayer()
        # Even at critical HP, ArbitrationLayer returns the state-appropriate action
        # (SafetyLayer handles HP override separately)
        action, ctx = arb.decide(f, {"quest_status": "ACTIVE", "has_mob": True,
                                      "quest_struct": {"objectives": [{"type": "kill"}]},
                                      "quest_system_ready": True,
                                      "hp_frac": 0.1}, {})
        # ArbitrationLayer returns "farm" — SafetyLayer would override to "heal"
        assert action == "farm"
