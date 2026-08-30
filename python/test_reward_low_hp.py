"""Self-learning needs a survival signal: low HP must be penalized, not just death.

If reward.py only penalizes death (-5.0), the Q-table learns "combat = death"
and the agent stops farming entirely. A low-HP penalty teaches the agent to
retreat/heal BEFORE dying — letting it learn survival autonomously instead of
being forced by a hard-coded override.

Run: python test_reward_low_hp.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reward import outcome_reward


def test_low_hp_penalized():
    before = {"hp_frac": 0.9, "deaths": 0, "quest_progress": 0}
    after = {"hp_frac": 0.15, "deaths": 0, "quest_progress": 0}
    r = outcome_reward(before, after, "INCONCLUSIVE")
    # Low HP with no death and no progress must be NEGATIVE — that is the
    # survival lesson. If it is >= 0, the agent has no reason to learn retreat.
    assert r < 0, f"expected negative reward for low HP, got {r}"
    print(f"GREEN: low-HP penalty = {r}")


def test_full_hp_no_penalty():
    before = {"hp_frac": 0.9, "deaths": 0, "quest_progress": 0}
    after = {"hp_frac": 0.95, "deaths": 0, "quest_progress": 0}
    r = outcome_reward(before, after, "INCONCLUSIVE")
    assert r >= 0, f"expected non-negative reward at full HP, got {r}"
    print(f"GREEN: full-HP reward = {r}")


if __name__ == "__main__":
    test_low_hp_penalized()
    test_full_hp_no_penalty()
    print("ALL GREEN")
