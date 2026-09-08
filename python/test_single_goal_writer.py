import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def _ws(phase="COMPLETE_OBJECTIVE", qid="q_a", cur=5, req=8, has_ready=False):
    return {
        "quest": {"id": qid, "phase": phase, "progress": cur, "required": req},
        "hp_frac": 0.9,
        "has_ready": has_ready,
    }


def test_fsm_is_single_writer_marks_source():
    from goal_fsm import GoalFSM, MIN_DWELL_STEPS
    import tempfile
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "g.json"))
    f.set("DO_OBJECTIVE", "q_a", source="fsm", step=MIN_DWELL_STEPS)
    assert f.goal_source == "fsm"


def test_advisory_write_does_not_change_goal():
    from goal_fsm import GoalFSM, MIN_DWELL_STEPS
    import tempfile
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "g.json"))
    f.set("DO_OBJECTIVE", "q_a", source="fsm", step=MIN_DWELL_STEPS)
    changed = f.suggest("TURN_IN", reason="llm says so")
    assert changed is False, "совет не должен менять цель"
    assert f.goal == "DO_OBJECTIVE:q_a"
    assert f.last_suggestion == "TURN_IN"


def test_suggestion_is_recorded_for_learning():
    from goal_fsm import GoalFSM, MIN_DWELL_STEPS
    import tempfile
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "g.json"))
    f.set("DO_OBJECTIVE", "q_a", source="fsm", step=MIN_DWELL_STEPS)
    f.suggest("TURN_IN", reason="bags full")
    assert f.last_suggestion == "TURN_IN"
    assert f.last_suggestion_reason == "bags full"


def test_goal_switch_counter_only_counts_real_changes():
    from goal_fsm import GoalFSM, MIN_DWELL_STEPS
    import tempfile
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "g.json"))
    f.set("DO_OBJECTIVE", "q_a", source="fsm", step=MIN_DWELL_STEPS)
    base = f.switch_count
    f.set("DO_OBJECTIVE", "q_a", source="fsm", step=MIN_DWELL_STEPS + 1)
    f.set("DO_OBJECTIVE", "q_a", source="fsm", step=MIN_DWELL_STEPS + 2)
    assert f.switch_count == base, "повторная запись той же цели — не смена"
    f.set("TURN_IN", "q_a", source="fsm", step=MIN_DWELL_STEPS * 3)
    assert f.switch_count == base + 1


def test_min_dwell_blocks_thrashing():
    from goal_fsm import GoalFSM, MIN_DWELL_STEPS
    import tempfile
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "g.json"))
    f.set("DO_OBJECTIVE", "q_a", source="fsm", step=100)
    ok = f.set("TURN_IN", "q_a", source="fsm", step=100 + MIN_DWELL_STEPS - 1)
    assert ok is False, "смена раньше min-dwell должна быть отклонена"
    assert f.goal == "DO_OBJECTIVE:q_a"
    ok2 = f.set("TURN_IN", "q_a", source="fsm", step=100 + MIN_DWELL_STEPS)
    assert ok2 is True and f.goal == "TURN_IN:q_a"


def test_death_forces_switch_ignoring_dwell():
    from goal_fsm import GoalFSM, MIN_DWELL_STEPS
    import tempfile
    f = GoalFSM(memory_path=os.path.join(tempfile.mkdtemp(), "g.json"))
    f.set("DO_OBJECTIVE", "q_a", source="fsm", step=MIN_DWELL_STEPS)
    ok = f.set("TURN_IN", "q_a", source="fsm", step=MIN_DWELL_STEPS + 1, force=True)
    assert ok is True and f.goal == "TURN_IN:q_a", "смерть/критический hp обязаны форсировать"
