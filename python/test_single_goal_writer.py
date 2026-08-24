import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def _ws(phase="COMPLETE_OBJECTIVE", qid="q_a", cur=5, req=8, has_ready=False):
    return {
        "quest": {"id": qid, "phase": phase, "progress": cur, "required": req},
        "hp_frac": 0.9,
        "has_ready": has_ready,
    }


def test_fsm_is_single_writer_marks_source():
    """Доказано по коду 2026-08-24: цель писали ТРИ места —
    play_autonomous:327 (FSM), play_autonomous:384 (LLM через apply_decision) и
    agent.py:304 (FSM внутри step, ЗАТИРАЛ решение LLM через 6 строк).
    Теперь у goal ровно один писатель, и он себя помечает."""
    from goal_fsm import GoalFSM
    import tempfile
    f = GoalFSM(path=os.path.join(tempfile.mkdtemp(), "g.json"))
    f.set("DO_OBJECTIVE", "q_a", source="fsm")
    assert f.goal_source == "fsm"


def test_advisory_write_does_not_change_goal():
    """LLM больше НЕ пишет цель: её вход — совет, который не меняет фазу.
    Иначе мы возвращаемся к goal_switches=0.71/шаг."""
    from goal_fsm import GoalFSM
    import tempfile
    f = GoalFSM(path=os.path.join(tempfile.mkdtemp(), "g.json"))
    f.set("DO_OBJECTIVE", "q_a", source="fsm")
    changed = f.suggest("TURN_IN", reason="llm says so")
    assert changed is False, "совет не должен менять цель"
    assert f.goal == "DO_OBJECTIVE"
    assert f.last_suggestion == "TURN_IN"


def test_suggestion_is_recorded_for_learning():
    """Совет сохраняется — по нему потом можно измерить, был ли он полезен."""
    from goal_fsm import GoalFSM
    import tempfile
    f = GoalFSM(path=os.path.join(tempfile.mkdtemp(), "g.json"))
    f.set("DO_OBJECTIVE", "q_a", source="fsm")
    f.suggest("SELL_REPAIR", reason="bags full")
    assert f.last_suggestion == "SELL_REPAIR"
    assert f.last_suggestion_reason == "bags full"


def test_goal_switch_counter_only_counts_real_changes():
    """Метрика goal_switches должна считать РЕАЛЬНЫЕ смены фазы, а не
    повторные записи той же цели (иначе цифра 0.71/шаг обманывает)."""
    from goal_fsm import GoalFSM
    import tempfile
    f = GoalFSM(path=os.path.join(tempfile.mkdtemp(), "g.json"))
    f.set("DO_OBJECTIVE", "q_a", source="fsm")
    base = f.switch_count
    f.set("DO_OBJECTIVE", "q_a", source="fsm")      # та же цель
    f.set("DO_OBJECTIVE", "q_a", source="fsm")
    assert f.switch_count == base, "повторная запись той же цели — не смена"
    f.set("TURN_IN", "q_a", source="fsm")
    assert f.switch_count == base + 1


def test_min_dwell_blocks_thrashing():
    """Контракт со-архитектора (Q11): даже легитимная смена не чаще, чем раз в
    MIN_DWELL_STEPS шагов, кроме форсирующих событий (смерть)."""
    from goal_fsm import GoalFSM, MIN_DWELL_STEPS
    import tempfile
    f = GoalFSM(path=os.path.join(tempfile.mkdtemp(), "g.json"))
    f.set("DO_OBJECTIVE", "q_a", source="fsm", step=100)
    ok = f.set("SELL_REPAIR", "q_a", source="fsm", step=100 + MIN_DWELL_STEPS - 1)
    assert ok is False, "смена раньше min-dwell должна быть отклонена"
    assert f.goal == "DO_OBJECTIVE"
    ok2 = f.set("SELL_REPAIR", "q_a", source="fsm", step=100 + MIN_DWELL_STEPS)
    assert ok2 is True and f.goal == "SELL_REPAIR"


def test_death_forces_switch_ignoring_dwell():
    from goal_fsm import GoalFSM
    import tempfile
    f = GoalFSM(path=os.path.join(tempfile.mkdtemp(), "g.json"))
    f.set("DO_OBJECTIVE", "q_a", source="fsm", step=100)
    ok = f.set("HEAL", "q_a", source="fsm", step=101, force=True)
    assert ok is True and f.goal == "HEAL", "смерть/критический hp обязаны форсировать"
