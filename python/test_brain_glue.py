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


def test_apply_decision_no_longer_writes_goal():
    """КОНТРАКТ ИЗМЕНЁН 2026-08-24 (аудит LLM: HARMFUL). Раньше LLM писала цель
    в FSM, но её решение затиралось через 6 строк вызовом update_from_world
    внутри agent.step(), при этом шаг замедлялся в 6 раз (0.30->1.80с).
    Теперь мнение LLM — только СОВЕТ: цель не меняется, совет сохраняется."""
    from goal_fsm import GoalFSM, TURN_IN
    f = GoalFSM(path=tempfile.mkdtemp() + "/g.json")
    f.set(TURN_IN, "q_old")
    from brain_glue import apply_decision
    applied = apply_decision(f, {"goal": "DO_OBJECTIVE", "reason": "active 6/10"})
    assert applied is False, "LLM больше не должна писать цель"
    assert f.goal == TURN_IN, "цель обязана остаться нетронутой"
    assert f.last_suggestion == "DO_OBJECTIVE", "совет должен быть записан"
    assert "active 6/10" in (f.last_suggestion_reason or "")


def test_apply_rejects_none_and_bad_goal():
    from goal_fsm import GoalFSM, TURN_IN
    f = GoalFSM(path=tempfile.mkdtemp() + "/g.json")
    f.set(TURN_IN, "q_old")
    from brain_glue import apply_decision
    assert apply_decision(f, None) is False
    assert apply_decision(f, {"goal": "CONQUER_WORLD"}) is False
    assert f.goal == TURN_IN          # FSM не тронут


def test_survive_maps_to_heal_in_suggestion_only():
    """SURVIVE по-прежнему нормализуется в HEAL, но попадает в СОВЕТ, а не в
    цель: выживанием управляют survival-гейты политики, не латентная LLM."""
    from goal_fsm import GoalFSM, HEAL
    f = GoalFSM(path=tempfile.mkdtemp() + "/g.json")
    f.set("DO_OBJECTIVE", "q_x")
    from brain_glue import apply_decision
    apply_decision(f, {"goal": "SURVIVE", "reason": "low hp"})
    assert f.goal == "DO_OBJECTIVE", "цель не должна меняться советом"
    assert f.last_suggestion == HEAL, "SURVIVE обязан нормализоваться в HEAL"
