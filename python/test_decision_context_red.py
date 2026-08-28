"""RED test: ONE DECISION CYCLE invariant.

Current bug: AutonomyLoop writes to policy.hints["masked_candidates"] and
policy.hints["autonomy_subgoal"], then Policy reads them as mutable state.
This creates a hidden IPC channel instead of an explicit decision context.

This test pins the invariant:
  Policy.decide() must depend ONLY on (info, ws, goal, context),
  NOT on mutable self.hints set by a previous caller.

Before fix: test FAILS (hints leak into decision).
After fix:  test PASSES (explicit context, no hints).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


def _make_policy():
    from policy import GoalManager
    from memory import ExperienceStore
    mem = ExperienceStore(path=":memory:")
    return GoalManager(mem, temperature=0.1)


def _fake_info_ws():
    """Minimal info/ws so policy.decide() doesn't crash."""
    info = {
        "player_class": "warrior",
        "inventory_by_id": {"baked_bread": 5},
        "inventory": [{"itemId": "baked_bread", "count": 5, "quality": "common"}],
        "quests": {"active": [], "ready": [], "done": []},
        "nearby": [],
        "in_combat": False,
    }
    ws = {
        "player_class": "warrior",
        "player": {"hp": 100, "maxHp": 100, "level": 1, "position": [0.0, 0.0]},
        "inventory_by_id": {"baked_bread": 5},
        "bag_capacity": 16,
        "quests_done": 0,
        "quest": {},
        "quest_status": None,
        "hp_frac": 1.0,
        "weak_mob_near": False,
        "giver_distance": 999,
        "distance_to_giver": 999,
    }
    return info, ws


def test_hints_do_not_leak_into_decide():
    """Invariant: policy.hints must NOT influence decide() output.

    If Autonomy writes hints["masked_candidates"] = ["explore"] and the next
    decide() call returns "explore" ONLY because of that hint (not because
    the world state justifies it), the invariant is violated.
    """
    pol = _make_policy()
    info, ws = _fake_info_ws()

    # Baseline: decision WITHOUT any hints
    pol.hints = {}
    action_baseline, _ = pol.decide(info, ws, goal="NO_QUEST")

    # Now simulate what Autonomy does: write masked_candidates hint
    pol.hints = {"masked_candidates": ["explore"]}
    action_with_hint, _ = pol.decide(info, ws, goal="NO_QUEST")

    # The hint must NOT silently override the decision.
    # If action_with_hint != action_baseline, hints are leaking.
    assert action_with_hint == action_baseline, (
        f"policy.hints leaked into decide(): "
        f"baseline={action_baseline!r}, with_hint={action_with_hint!r}. "
        f"hints={pol.hints!r}"
    )


def test_autonomy_subgoal_hint_does_not_force():
    """Invariant: autonomy_subgoal hint must NOT be a hidden force command.

    Autonomy writes hints["autonomy_subgoal"] = {"skill": "accept_quest"}.
    Policy may PREFER it, but must not be silently forced by mutable state.
    """
    pol = _make_policy()
    info, ws = _fake_info_ws()

    pol.hints = {}
    action_baseline, _ = pol.decide(info, ws, goal="NO_QUEST")

    # Simulate Autonomy writing a forced skill hint
    pol.hints = {"autonomy_subgoal": {"skill": "accept_quest"}}
    action_with_hint, _ = pol.decide(info, ws, goal="NO_QUEST")

    # If the hint silently forces a different action, it's a hidden command bus.
    assert action_with_hint == action_baseline, (
        f"autonomy_subgoal hint leaked: "
        f"baseline={action_baseline!r}, with_hint={action_with_hint!r}. "
        f"hints={pol.hints!r}"
    )


def test_explicit_context_replaces_hints():
    """After fix: policy.decide() accepts explicit context, ignores hints.

    This test will PASS only after DecisionContext is implemented.
    Before fix: skipped (no context parameter exists).
    """
    import inspect
    from policy import GoalManager
    sig = inspect.signature(GoalManager.decide)
    params = list(sig.parameters.keys())

    # After fix: "context" must be an accepted parameter
    assert "context" in params, (
        f"GoalManager.decide() must accept 'context' parameter. "
        f"Current params: {params}"
    )
