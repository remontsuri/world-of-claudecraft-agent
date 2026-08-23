import os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))


def test_build_world_payload_shape():
    from brain_glue import build_brain_payload
    ws = {"quest": {"id": "q_bones", "phase": "ACTIVE", "progress": 6,
                    "required": 10, "giver_distance": 83.0},
          "hp_frac": 0.71, "danger": False}
    info = {"player_pos": [1, 2], "player": {"dead": False}}
    p = build_brain_payload(ws, info, "q_bones")
    assert p["quest"]["id"] == "q_bones"
    assert p["giver_distance"] == 83.0
    assert p["player"]["hp_frac"] == 0.71
    assert p["player"]["dead"] is False
    assert p["bag_slots"] == 0


def test_apply_decision_sets_fsm():
    from goal_fsm import GoalFSM, DO_OBJECTIVE, TURN_IN
    f = GoalFSM(path=tempfile.mkdtemp() + "/g.json")
    f.set(TURN_IN, "q_old")
    from brain_glue import apply_decision
    applied = apply_decision(f, {"goal": "DO_OBJECTIVE", "reason": "active 6/10"})
    assert applied and f.goal == DO_OBJECTIVE and f.quest_id == "q_old"


def test_apply_rejects_none_and_bad_goal():
    from goal_fsm import GoalFSM, TURN_IN
    f = GoalFSM(path=tempfile.mkdtemp() + "/g.json")
    f.set(TURN_IN, "q_old")
    from brain_glue import apply_decision
    assert apply_decision(f, None) is False
    assert apply_decision(f, {"goal": "CONQUER_WORLD"}) is False
    assert f.goal == TURN_IN          # FSM не тронут


def test_survive_maps_to_heal():
    from goal_fsm import GoalFSM, HEAL
    f = GoalFSM(path=tempfile.mkdtemp() + "/g.json")
    f.set("DO_OBJECTIVE", "q_x")
    from brain_glue import apply_decision
    apply_decision(f, {"goal": "SURVIVE", "reason": "low hp"})
    assert f.goal == HEAL
