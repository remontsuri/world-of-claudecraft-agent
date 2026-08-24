import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def _snap(active=(), ready=(), done=()):
    def q(qid, cur, req, npc=None):
        d = {"id": qid, "objectives": [{"current": cur, "required": req}]}
        if npc:
            d["turnInNpc"] = {"x": npc[0], "z": npc[1]}
        return d
    return {
        "player_pos": [0.0, 0.0],
        "quests": {
            "active": [q(*a) for a in active],
            "ready": [q(*r) for r in ready],
            "done": [{"id": x} for x in done],
        },
        "nearby": [],
    }


def test_unknown_quest_is_available_not_active():
    """Основа Goal Manager: квест, которого нет в логе, доступен для ACCEPT."""
    from quest_truth import QuestTruth
    qt = QuestTruth(_snap())
    assert qt.phase("q_new") == "AVAILABLE"
    assert qt.can_accept("q_new") is True


def test_active_quest_cannot_be_accepted_again():
    """ЯДРО требования пользователя: «квест уже взят → агент снова пытается
    взять квест у NPC» должно стать ФИЗИЧЕСКИ невозможным."""
    from quest_truth import QuestTruth
    qt = QuestTruth(_snap(active=[("q_bones", 5, 8)]))
    assert qt.phase("q_bones") == "COMPLETE_OBJECTIVE"
    assert qt.can_accept("q_bones") is False


def test_ready_quest_phase_is_turn_in():
    from quest_truth import QuestTruth
    qt = QuestTruth(_snap(ready=[("q_bones", 8, 8, (4.0, -56.0))]))
    assert qt.phase("q_bones") == "TURN_IN"
    assert qt.can_turn_in("q_bones") is False       # гивер далеко (по умолчанию)


def test_turn_in_allowed_only_within_interact_range():
    """turn_in при дистанции > 7yd сервер отклоняет молча — запрещаем заранее."""
    from quest_truth import QuestTruth
    snap = _snap(ready=[("q_bones", 8, 8, (3.0, 4.0))])   # dist = 5.0 от [0,0]
    qt = QuestTruth(snap)
    assert qt.giver_distance("q_bones") == 5.0
    assert qt.can_turn_in("q_bones") is True
    far = _snap(ready=[("q_bones", 8, 8, (30.0, 40.0))])  # dist = 50
    assert QuestTruth(far).can_turn_in("q_bones") is False


def test_done_quest_phase():
    from quest_truth import QuestTruth
    qt = QuestTruth(_snap(done=["q_old"]))
    assert qt.phase("q_old") == "DONE"
    assert qt.can_accept("q_old") is False


def test_progress_reports_current_and_required():
    from quest_truth import QuestTruth
    qt = QuestTruth(_snap(active=[("q_bones", 5, 8)]))
    assert qt.progress("q_bones") == (5, 8)


def test_objective_complete_but_not_ready_still_needs_return():
    """Цели выполнены, но квест ещё в active (сервер не перевёл в ready):
    фаза — возврат к гиверу, не сдача."""
    from quest_truth import QuestTruth
    qt = QuestTruth(_snap(active=[("q_bones", 8, 8, (30.0, 40.0))]))
    assert qt.phase("q_bones") == "RETURN_TO_GIVER"


def test_pick_target_prefers_ready_then_closest_objective():
    """Одна активная цель: сначала готовый к сдаче, иначе ближайший к завершению."""
    from quest_truth import QuestTruth
    snap = _snap(active=[("q_a", 1, 10), ("q_b", 7, 8)],
                 ready=[("q_c", 5, 5, (1.0, 1.0))])
    qt = QuestTruth(snap)
    assert qt.pick_target() == "q_c"
    snap2 = _snap(active=[("q_a", 1, 10), ("q_b", 7, 8)])
    assert QuestTruth(snap2).pick_target() == "q_b"


def test_no_quests_returns_none_target():
    from quest_truth import QuestTruth
    assert QuestTruth(_snap()).pick_target() is None


def test_all_phases_are_known_values():
    """Фазы — закрытый enum, чтобы Goal Manager не получил мусор."""
    from quest_truth import PHASES, QuestTruth
    qt = QuestTruth(_snap(active=[("q_a", 1, 3)], ready=[("q_b", 2, 2, (1.0, 1.0))],
                          done=["q_c"]))
    for qid in ("q_a", "q_b", "q_c", "q_unknown"):
        assert qt.phase(qid) in PHASES, f"{qid} -> {qt.phase(qid)}"
