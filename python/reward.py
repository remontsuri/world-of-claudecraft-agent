"""Reward computation — from FACT, not from our interpretation.

Per user 2026-08-16: Memory.learn() must NOT be trained on pre-assigned REWARD
independent of the real outcome. The agent must learn from WORLD CONSEQUENCES, not
from our opinion of whether an action was "good". So:

- reward is a pure function of (before, after, verdict, outcome_kind).
- coefficients are CONFIG (not quest-specific logic).
- drift_far is derived from the MEASURED change in distance_to_giver, NOT from a
  hard rule "farm was bad". If the world shows the player ended up far from the
  giver with no progress, that's a real cost the agent can learn — but it's
  computed from the delta, not assigned by us.
- ENV_ERROR (server crash) is a SEPARATE outcome: it must NOT produce negative
  reward. The agent died/stopped due to infrastructure, not a game decision.
  Training on ENV_ERROR would teach "don't farm because the server sometimes
  crashes" — which is wrong (the problem is the environment, not the action).
"""

from typing import Dict, Optional


# ---- configuration (coefficients, not logic) -------------------------------
WEIGHTS = {
    "xp": 0.001,
    "copper": 0.01,
    "quest_progress": 1.0,
    "quests_done": 5.0,
    # A kill must be materially more valuable than a neutral explore/heal step.
    # The old 0.2 signal was too weak while early combat also incurred HP-loss
    # penalties. SUCCESS still adds its separate measured-world bonus.
    "kills": 0.5,
    "loot_items": 0.05,
    "death": -5.0,
    "success_bonus": 0.5,
    "failure_penalty": -0.3,
    "drift_per_unit": -0.01,
    "drift_cap": -2.0,
    "dist_progress": 0.02,
    "low_hp": -1.5,
}


def _safe_get(d: Dict, *keys, default=0):
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return default
    return d if d is not None else default


def outcome_reward(
    before: Dict,
    after: Dict,
    verdict: str,
    outcome_kind: str = "OK",
    cfg: Optional[Dict] = None,
) -> float:
    """Compute reward strictly from observed world deltas."""
    c = cfg or WEIGHTS
    if outcome_kind == "ENV_ERROR":
        return 0.0

    reward = 0.0
    reward += max(0.0, _safe_get(after, "xp") - _safe_get(before, "xp")) * c["xp"]
    reward += max(0.0, _safe_get(after, "copper") - _safe_get(before, "copper")) * c["copper"]
    reward += max(0.0, _safe_get(after, "quest_progress") - _safe_get(before, "quest_progress")) * c["quest_progress"]
    reward += max(0.0, _safe_get(after, "quests_done") - _safe_get(before, "quests_done")) * c["quests_done"]
    reward += max(0.0, _safe_get(after, "kills") - _safe_get(before, "kills")) * c["kills"]
    reward += max(0.0, _safe_get(after, "inv_slots") - _safe_get(before, "inv_slots")) * c["loot_items"]

    died = _safe_get(after, "deaths") > _safe_get(before, "deaths")
    if died:
        reward += c["death"]

    if not died:
        d_before = _safe_get(before, "distance_to_giver")
        d_after = _safe_get(after, "distance_to_giver")
        if d_after < d_before:
            reward += (d_before - d_after) * c["dist_progress"]
        elif d_after > d_before:
            drift = d_after - d_before
            reward += max(c["drift_cap"], drift * c["drift_per_unit"])

    world_delta_seen = abs(reward) > 1e-9
    if verdict == "SUCCESS":
        if world_delta_seen:
            reward += c["success_bonus"]
    elif verdict == "FAILURE":
        reward += c["failure_penalty"]

    hp_loss = _safe_get(before, "hp_frac") - _safe_get(after, "hp_frac")
    if hp_loss > 0:
        reward += hp_loss * c["low_hp"]

    return round(reward, 4)
