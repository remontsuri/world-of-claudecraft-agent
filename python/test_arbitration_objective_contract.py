import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from arbitration_layer import ArbitrationLayer, ACTION_FARM
from goal_fsm import QuestState


class _FSM:
    state = QuestState.DO_OBJECTIVE
    quest_giver = None
    active_quest = {"id": "q_wolves"}


def _ws():
    return {
        "quest_status": "ACTIVE",
        "quest_system_ready": True,
        "has_mob": True,
        # This is the canonical key emitted by world_state.build_world_state().
        "quest": {
            "id": "q_wolves",
            "accepted": True,
            "objectives": [{
                "type": "kill",
                "targetMobId": "mire_prowler",
                "current": 0,
                "required": 8,
            }],
        },
    }


def test_do_objective_reads_canonical_quest_objectives():
    arb = ArbitrationLayer()
    action, ctx = arb.decide(_FSM(), _ws(), {"nearby": []})
    assert action == ACTION_FARM
    assert ctx["targetMobId"] == "mire_prowler"


def test_completed_objective_is_not_used_as_target():
    ws = _ws()
    ws["quest"]["objectives"][0]["current"] = 8
    arb = ArbitrationLayer()
    action, ctx = arb.decide(_FSM(), ws, {"nearby": []})
    assert action == "explore"
    assert "targetMobId" not in ctx


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
