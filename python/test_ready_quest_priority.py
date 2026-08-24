import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from world_state import build_world_state


def _info(active=(), ready=(), pos=(0.0, 0.0)):
    def mk(qid, cur, req, npc, state):
        d = {"id": qid, "state": state,
             "objectives": [{"current": cur, "required": req}]}
        if npc:
            d["turnInNpc"] = {"x": npc[0], "z": npc[1]}
        return d
    return {
        "player": {"hp": 100, "maxHp": 100, "dead": False},
        "player_pos": [pos[0], pos[1]],
        "nearby": [], "inventory": [],
        "quests": {
            "active": [mk(*a, "active") for a in active],
            "ready": [mk(*r, "ready") for r in ready],
            "done": [],
        },
    }


def test_ready_quest_wins_over_active_with_known_giver():
    """Измерено на живом мире 2026-08-24: агент 37 шагов сидел в DO_OBJECTIVE,
    хотя q_prof_workorder_loom был ГОТОВ (6/6). Причина: выбор квеста брал
    первый с известным гивером (q_greyjaw 0/1), а готовность не учитывал."""
    info = _info(active=[("q_greyjaw", 0, 1, (50.0, 50.0))],
                 ready=[("q_loom", 6, 6, None)])
    ws = build_world_state(info)
    assert ws["quest"]["id"] == "q_loom", f"выбран {ws['quest']['id']}, а не готовый"
    assert ws["quest"]["phase"] == "READY"
    assert ws["quest"]["complete"] is True


def test_ready_with_known_giver_preferred_among_ready():
    """Среди готовых предпочитаем того, к кому знаем дорогу."""
    info = _info(ready=[("q_far", 3, 3, None), ("q_near", 2, 2, (3.0, 4.0))])
    ws = build_world_state(info)
    assert ws["quest"]["id"] == "q_near"
    assert ws["quest"]["giver_known"] is True


def test_active_chosen_when_nothing_ready():
    info = _info(active=[("q_a", 1, 5, (10.0, 0.0))])
    ws = build_world_state(info)
    assert ws["quest"]["id"] == "q_a"
    assert ws["quest"]["phase"] == "ACTIVE"


def test_quest_status_reflects_ready_choice():
    """quest_status должен говорить READY_TO_TURN_IN, иначе FSM не переведёт фазу."""
    info = _info(active=[("q_greyjaw", 0, 1, (50.0, 50.0))],
                 ready=[("q_loom", 6, 6, (2.0, 0.0))])
    ws = build_world_state(info)
    assert ws["quest_status"] == "READY_TO_TURN_IN", ws["quest_status"]
