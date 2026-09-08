from pathlib import Path
ROOT = Path(__file__).resolve().parent
ACTIONS = (ROOT.parent.parent / "world-of-claudecraft" / "src" / "bridge" / "actions.cjs").read_text(encoding="utf-8")
MEMORY = (ROOT / "memory.py").read_text(encoding="utf-8")
POLICY = (ROOT / "policy.py").read_text(encoding="utf-8")
AUTONOMY = (ROOT / "autonomy.py").read_text(encoding="utf-8")
MASK = (ROOT / "action_mask.py").read_text(encoding="utf-8")

def test_farm_uses_verified_move_facing_path():
    farm = ACTIONS[ACTIONS.index("case 0:"):ACTIONS.index("case 1:")]
    assert "g.controller.move({ [kind]: true }, desired);" in farm
    assert "g.controller.face(desired)" not in farm

def test_navigation_inconclusive_does_not_schedule_recovery():
    assert "navigation_inconclusive" in AUTONOMY
    assert 'if result != "SUCCESS" and not navigation_inconclusive:' in AUTONOMY

def test_planner_subgoal_does_not_force_normal_policy_action():
    """STREAM J6: AutonomyLoop does not force skill directly — signals instead."""
    assert "forced = sg_skill" not in AUTONOMY
    assert "forced_skill" not in AUTONOMY
    assert "signals" in AUTONOMY

def test_navigate_is_learnable_in_objective_phase():
    assert 'if goal_phase == "DO_OBJECTIVE" and ws.get("quest", {}).get("id"):' in POLICY
    assert 'if "navigate" not in cands:' in POLICY

def test_endpoint_actions_are_persisted():
    assert '"navigate", "flee"]' in MEMORY

def test_flee_is_not_unconditionally_injected():
    assert 'ALWAYS_AVAILABLE = ["explore", "navigate"]' in MASK
