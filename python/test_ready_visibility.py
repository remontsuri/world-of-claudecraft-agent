import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def test_payload_includes_ready_quests():
    from brain_glue import build_brain_payload
    ws = {"quest": {"id": "q_greyjaw", "phase": "ACTIVE", "progress": 0,
                    "required": 1, "giver_distance": 40.0},
          "hp_frac": 0.9}
    info = {"player": {"dead": False},
            "quests": {"active": [{"id": "q_greyjaw"}],
                       "ready": [{"id": "q_prof_workorder_kitchens",
                                  "objectives": [{"current": 8, "required": 8}],
                                  "turnInNpc": None}]}}
    p = build_brain_payload(ws, info, "q_greyjaw")
    assert p.get("ready_quests") == [
        {"id": "q_prof_workorder_kitchens", "progress": 8, "required": 8}]


def test_payload_empty_ready_list():
    from brain_glue import build_brain_payload
    ws = {"quest": {"id": "q_a", "phase": "ACTIVE"}, "hp_frac": 0.9}
    info = {"player": {"dead": False}, "quests": {"active": [], "ready": []}}
    p = build_brain_payload(ws, info, "q_a")
    assert p.get("ready_quests") == []


def test_system_prompt_mentions_ready_rule():
    import llm_brain
    assert "READY" in llm_brain._SYSTEM
