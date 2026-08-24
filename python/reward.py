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
    "xp": 0.001,            # per xp gained
    "copper": 0.01,         # per copper gained
    "quest_progress": 1.0,  # per objective-count unit gained
    "quests_done": 5.0,     # per quest turned in
    "kills": 0.2,           # per kill
    "loot_items": 0.05,     # per inventory slot gained
    "death": -5.0,          # per death
    "success_bonus": 0.5,   # verifier SUCCESS
    "failure_penalty": -0.3,  # verifier FAILURE
    # drift: measured cost of ending far from the quest giver with no progress.
    # coefficient small; only bites when distance grew AND progress didn't.
    "drift_per_unit": -0.01,
    "drift_cap": -2.0,
    "dist_progress": 0.02,   # reward per unit distance DECREASED toward giver
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
    outcome_kind: str = "OK",       # "OK" | "ENV_ERROR" | "INCONCLUSIVE"
    cfg: Optional[Dict] = None,
) -> float:
    """Compute reward strictly from observed world deltas.

    before/after: WorldState dicts (player/xp/copper/quests/kills/inventory/distance).
    verdict: "SUCCESS" | "PARTIAL" | "FAILURE" | "INCONCLUSIVE" (from verifier).
    outcome_kind: "OK" (normal) | "ENV_ERROR" (server crash) | "INCONCLUSIVE".
    """
    c = cfg or WEIGHTS
    # ENV_ERROR is infrastructure, NOT a game outcome. Never train on it.
    if outcome_kind == "ENV_ERROR":
        return 0.0

    reward = 0.0
    reward += max(0.0, _safe_get(after, "xp") - _safe_get(before, "xp")) * c["xp"]
    reward += max(0.0, _safe_get(after, "copper") - _safe_get(before, "copper")) * c["copper"]
    reward += max(0.0, _safe_get(after, "quest_progress") - _safe_get(before, "quest_progress")) * c["quest_progress"]
    reward += max(0.0, _safe_get(after, "quests_done") - _safe_get(before, "quests_done")) * c["quests_done"]
    reward += max(0.0, _safe_get(after, "kills") - _safe_get(before, "kills")) * c["kills"]
    # inventory growth (loot) — count slots, not value
    reward += max(0.0, _safe_get(after, "inv_slots") - _safe_get(before, "inv_slots")) * c["loot_items"]

    died = _safe_get(after, "deaths") > _safe_get(before, "deaths")
    if died:
        reward += c["death"]

    # distance-to-giver progress: reward DECREASING distance (moving toward the
    # giver), even if still far. This is measured from the delta, not a rule.
    # Without it, return_to_giver gets no positive signal (short-nav can't close
    # 500u in one call) and the agent never learns to head back.
    #
    # MEASURED EXCEPTION (2026-08-17, _diag_death.py): dying RESPAWNS the player
    # next to the quest giver. A death therefore produces a huge apparent
    # "distance closed" (observed 97.4 -> 4.0 in one call) that no action earned.
    # Crediting it would teach "dying is a good way to get back" — a false lesson
    # from a teleport, not from navigation. So distance progress is only credited
    # when the player did NOT die during the step. Verified clean case:
    # navigation alone closed 59.8 -> 36.0 with deaths unchanged.
    if not died:
        d_before = _safe_get(before, "distance_to_giver")
        d_after = _safe_get(after, "distance_to_giver")
        if d_after < d_before:
            reward += (d_before - d_after) * c["dist_progress"]
        elif d_after > d_before:
            # DRIFT: the agent ended up FARTHER from the quest giver than before.
            # This is a real, measurable cost (it must now re-cover that distance)
            # and MUST be penalized, otherwise return_to_giver never learns to head
            # back and the agent just farms forever. drift_per_unit was declared in
            # WEIGHTS but previously never applied — that is the bug. Cap it so a
            # single respawn teleport (huge delta) can't nuke the Q-value.
            drift = (d_after - d_before)
            reward += max(c["drift_cap"], drift * c["drift_per_unit"])

    # ШАГ 2 спеки (2026-08-24): success_bonus ТОЛЬКО при реальном изменении
    # мира. Раньше он платился за ЛЮБОЙ вердикт SUCCESS, и это давало
    # наградной тредмилл: измерено 200 из 226 очков за 1000 шагов (88%)
    # приходили именно оттуда, тогда как сдача квеста стоила 5.0 — то есть
    # 2.2% от рутины. Агент рационально выбирал крутиться на месте:
    # return_to_giver, стоящий у гивера, и sell_junk без джанка возвращают
    # SUCCESS, ничего не меняя в мире.
    # Мировая дельта = всё, что уже начислено выше (xp/copper/прогресс/
    # киллы/лут/дистанция/смерть). Если она нулевая, бонус не платим.
    world_delta_seen = abs(reward) > 1e-9
    if verdict == "SUCCESS":
        if world_delta_seen:
            reward += c["success_bonus"]
    elif verdict == "FAILURE":
        # провал наказывается ВСЕГДА, независимо от дельты: попытка была
        reward += c["failure_penalty"]

    return round(reward, 4)
