"""test_decision_trace_smoke.py — verify DecisionTrace produces valid JSONL."""
import json
import os
import sys
import tempfile

# Use a temp dir for the test
tmpdir = tempfile.mkdtemp()
os.chdir(tmpdir)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "python"))

from decision_trace import (
    DecisionTrace,
    make_decision_trace,
    write_decision_trace,
    decompose_reward,
    _world_state_hash,
)


def test_world_state_hash_stable():
    ws = {"hp_frac": 0.5, "quest_status": "NONE", "has_mob": True}
    h1 = _world_state_hash(ws)
    h2 = _world_state_hash(ws)
    assert h1 == h2, f"Hash not stable: {h1} != {h2}"
    print("PASS: world_state_hash is stable")


def test_world_state_hash_changes():
    ws1 = {"hp_frac": 0.5, "quest_status": "NONE"}
    ws2 = {"hp_frac": 0.4, "quest_status": "NONE"}
    h1 = _world_state_hash(ws1)
    h2 = _world_state_hash(ws2)
    assert h1 != h2, "Hash should change when state changes"
    print("PASS: world_state_hash changes with state")


def test_decompose_reward():
    before = {"xp": 100, "copper": 50, "kills": 2, "deaths": 0, "hp_frac": 0.8, "distance_to_giver": 30.0, "quest_progress": 0.0, "inv_slots": 5, "quests_done": 0}
    after = {"xp": 110, "copper": 50, "kills": 3, "deaths": 0, "hp_frac": 0.75, "distance_to_giver": 25.0, "quest_progress": 0.5, "inv_slots": 6, "quests_done": 0}
    comp = decompose_reward(before, after, "SUCCESS", "OK")
    assert "xp" in comp, f"Missing xp component: {comp}"
    assert "kills" in comp, f"Missing kills component: {comp}"
    assert "quest_progress" in comp, f"Missing quest_progress: {comp}"
    assert "success_bonus" in comp, f"Missing success_bonus: {comp}"
    assert "dist_progress" in comp, f"Missing dist_progress: {comp}"
    print(f"PASS: decompose_reward returns {len(comp)} components: {list(comp.keys())}")


def test_decompose_reward_env_error():
    comp = decompose_reward({}, {}, "FAILURE", "ENV_ERROR")
    assert comp == {"env_error": 0.0}, f"ENV_ERROR should return only env_error: {comp}"
    print("PASS: decompose_reward handles ENV_ERROR")


def test_make_decision_trace():
    ws_before = {"hp_frac": 0.8, "quest_status": "ACTIVE", "quest": {"id": "q123"}, "target_mob_id": "152|forest_wolf", "kills": 2, "xp": 100, "distance_to_giver": 30.0}
    ws_after = {"hp_frac": 0.75, "quest_status": "ACTIVE", "quest": {"id": "q123"}, "target_mob_id": "152|forest_wolf", "kills": 3, "xp": 110, "distance_to_giver": 28.0}
    trace = make_decision_trace(
        step=42,
        ws_before=ws_before,
        ws_after=ws_after,
        fsm_phase_before="DO_OBJECTIVE",
        fsm_phase_after="DO_OBJECTIVE",
        planner_subgoal="KILL",
        candidate_actions=["farm", "loot", "explore"],
        policy_scores={"farm": 1.5, "loot": 0.3, "explore": 0.8},
        arbitration_reason="policy",
        action="farm",
        verdict="SUCCESS",
        outcome_kind="OK",
        reward=1.5,
        reward_components={"xp": 0.1, "kills": 0.5, "success_bonus": 0.5, "dist_progress": 0.1},
        duration_ms=12.5,
        ctx={"targetMobId": "152"},
    )
    assert trace.step == 42
    assert trace.chosen_action == "farm"
    assert trace.verifier_result == "SUCCESS"
    assert trace.objective_id == "q123"
    assert trace.target_id == "152|forest_wolf"
    assert "kills_delta" in trace.progress
    assert trace.progress["kills_delta"] == 1.0
    assert "xp_delta" in trace.progress
    assert trace.progress["xp_delta"] == 10.0
    print(f"PASS: DecisionTrace constructed (id={trace.decision_id[:8]}..., {len(trace.progress)} progress fields)")


def test_write_decision_trace():
    import importlib
    import decision_trace
    importlib.reload(decision_trace)

    # Clean slate
    if os.path.exists(decision_trace.TRACE_PATH):
        os.remove(decision_trace.TRACE_PATH)

    ws_before = {"hp_frac": 1.0, "quest_status": "NONE"}
    ws_after = {"hp_frac": 1.0, "quest_status": "NONE"}
    trace = make_decision_trace(
        step=1,
        ws_before=ws_before,
        ws_after=ws_after,
        fsm_phase_before="QUEST_NONE",
        fsm_phase_after="QUEST_NONE",
        planner_subgoal=None,
        candidate_actions=["explore", "farm"],
        policy_scores={"explore": 0.5, "farm": 0.0},
        arbitration_reason="policy",
        action="explore",
        verdict="INCONCLUSIVE",
        outcome_kind="OK",
        reward=0.0,
        reward_components={},
        duration_ms=5.0,
        ctx={},
    )
    write_decision_trace(trace)

    assert os.path.exists(decision_trace.TRACE_PATH), f"Trace file not created at {decision_trace.TRACE_PATH}"
    with open(decision_trace.TRACE_PATH, "r") as f:
        lines = f.readlines()
    assert len(lines) == 1, f"Expected 1 line, got {len(lines)}"
    parsed = json.loads(lines[0])
    assert parsed["step"] == 1
    assert parsed["chosen_action"] == "explore"
    assert "decision_id" in parsed
    assert "world_state_hash" in parsed
    assert len(parsed) == 19, f"Expected 19 fields, got {len(parsed)}"
    print(f"PASS: DecisionTrace written to JSONL and parsed back ({len(parsed)} fields)")


if __name__ == "__main__":
    test_world_state_hash_stable()
    test_world_state_hash_changes()
    test_decompose_reward()
    test_decompose_reward_env_error()
    test_make_decision_trace()
    test_write_decision_trace()
    print("\nAll tests passed!")
