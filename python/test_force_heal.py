"""
RED -> GREEN: agent must FORCE heal when hp_frac < 0.2, bypassing the policy
softmax. Root cause (verified in code, 2026-08-30):

- agent.py calls self.policy.decide(...) for the real action (line 433).
- policy.py:520-522 only APPENDS SKILL_HEAL to candidates when hp_frac < 1.0
  (almost always) — it does NOT force it. Softmax can still pick explore/farm.
- GoalFSM.decide() has `if hp_frac < 0.2: return "heal"` (goal_fsm.py:229-230)
  but that method is NEVER called from the live path (dead branch).

So at hp=0.03 the agent picked explore (INCONCLUSIVE) and died. The fix: a
hard override in agent.py BEFORE/after policy.decide when hp_frac < 0.2.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent as A


def test_should_force_heal():
    # module-level helper must exist and trigger at critical hp
    assert hasattr(A, "should_force_heal"), "agent.should_force_heal missing"
    assert A.should_force_heal({"hp_frac": 0.03}) is True, "must force heal at 3% hp"
    assert A.should_force_heal({"hp_frac": 0.19}) is True, "must force heal < 0.2"
    assert A.should_force_heal({"hp_frac": 0.20}) is False, "0.20 is NOT critical"
    assert A.should_force_heal({"hp_frac": 0.50}) is False, "half hp is not critical"
    assert A.should_force_heal({"hp_frac": 1.0}) is False, "full hp is not critical"


if __name__ == "__main__":
    try:
        test_should_force_heal()
        print("GREEN: should_force_heal correct")
    except AssertionError as e:
        print("RED:", e)
