"""decision_trace.py — canonical forensic record for every agent action.

One DecisionTrace per decision, written exactly once to decision_trace.jsonl.
Replaces the fragmented telemetry in decision_log.jsonl, _cycle.log, and
step_trace.json with a single replayable record.

Design:
    Observation -> FSM -> ArbitrationLayer -> Policy -> Skill -> Verifier -> Reward
    At the end of _cycle(), we have ALL the data needed to construct one trace.

Invariants:
    1. One record per decision (never 0, never 2).
    2. Atomic write (single json.dumps + "\n").
    3. Telemetry never crashes the agent (try/except everywhere).
    4. world_state_hash is stable (canonical JSON of ws_before, sorted keys).
    5. policy_scores is the FINAL input to softmax (after all weighting).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ---- configuration ----
TRACE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "decision_trace.jsonl"
)


def _canonical_json(obj: Any) -> str:
    """Stable JSON representation for hashing (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _world_state_hash(ws: Dict) -> str:
    """SHA-256 of canonical world state JSON. Stable across runs."""
    return hashlib.sha256(_canonical_json(ws).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class DecisionTrace:
    """Canonical forensic record for one agent decision.

    Every action must be replayable from one JSONL record.
    """

    decision_id: str
    step: int
    world_state_hash: str
    objective_id: Optional[str] = None
    target_id: Optional[str] = None
    fsm_phase_before: Optional[str] = None
    fsm_phase_after: Optional[str] = None
    planner_subgoal: Optional[str] = None
    candidate_actions: List[str] = field(default_factory=list)
    policy_scores: Dict[str, float] = field(default_factory=dict)
    arbitration_reason: str = "policy"
    chosen_action: str = ""
    verifier_result: str = ""
    outcome_kind: str = "OK"
    progress: Dict[str, float] = field(default_factory=dict)
    reward: float = 0.0
    reward_components: Dict[str, float] = field(default_factory=dict)
    duration_ms: float = 0.0
    ctx: Dict[str, Any] = field(default_factory=dict)


def write_decision_trace(trace: DecisionTrace) -> None:
    """Append one DecisionTrace to decision_trace.jsonl. Atomic write.

    Telemetry must never crash the agent — any error is silently swallowed
    (same discipline as _log_decision in policy.py).
    """
    try:
        line = json.dumps(asdict(trace), ensure_ascii=False, default=str) + "\n"
        with open(TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass  # telemetry must never crash the agent


def make_decision_trace(
    *,
    step: int,
    ws_before: Dict,
    ws_after: Dict,
    fsm_phase_before: Optional[str],
    fsm_phase_after: Optional[str],
    planner_subgoal: Optional[str],
    candidate_actions: List[str],
    policy_scores: Dict[str, float],
    arbitration_reason: str,
    action: str,
    verdict: str,
    outcome_kind: str,
    reward: float,
    reward_components: Dict[str, float],
    duration_ms: float,
    ctx: Dict[str, Any],
) -> DecisionTrace:
    """Construct a DecisionTrace from the data available at the end of _cycle().

    This is the SINGLE factory function — all DecisionTrace instances are
    created here so the field mapping is in one place.
    """
    # objective_id: quest id or target mob id
    objective_id = None
    q = ws_before.get("quest") or {}
    if q.get("id"):
        objective_id = str(q["id"])
    elif ws_before.get("target_mob_id"):
        objective_id = str(ws_before["target_mob_id"])

    # target_id: specific mob instance
    target_id = ws_before.get("target_mob_id")

    # progress: measured world deltas
    progress = {}
    for key, before_key, after_key in [
        ("xp_delta", "xp", "xp"),
        ("copper_delta", "copper", "copper"),
        ("kills_delta", "kills", "kills"),
        ("deaths_delta", "deaths", "deaths"),
    ]:
        b = ws_before.get(before_key, 0) or 0
        a = ws_after.get(after_key, 0) or 0
        delta = a - b
        if abs(delta) > 1e-9:
            progress[key] = round(delta, 4)

    # distance delta
    d_before = ws_before.get("distance_to_giver")
    d_after = ws_after.get("distance_to_giver")
    if d_before is not None and d_after is not None:
        dist_delta = d_before - d_after  # positive = got closer
        if abs(dist_delta) > 1e-9:
            progress["dist_delta"] = round(dist_delta, 2)

    # quest progress delta
    qp_before = ws_before.get("quest_progress", 0) or 0
    qp_after = ws_after.get("quest_progress", 0) or 0
    qp_delta = qp_after - qp_before
    if abs(qp_delta) > 1e-9:
        progress["quest_progress_delta"] = round(qp_delta, 4)

    return DecisionTrace(
        decision_id=str(uuid.uuid4()),
        step=step,
        world_state_hash=_world_state_hash(ws_before),
        objective_id=objective_id,
        target_id=target_id,
        fsm_phase_before=fsm_phase_before,
        fsm_phase_after=fsm_phase_after,
        planner_subgoal=planner_subgoal,
        candidate_actions=list(candidate_actions),
        policy_scores={k: round(v, 6) for k, v in policy_scores.items()},
        arbitration_reason=arbitration_reason,
        chosen_action=action,
        verifier_result=verdict,
        outcome_kind=outcome_kind,
        progress=progress,
        reward=round(reward, 6),
        reward_components={k: round(v, 6) for k, v in reward_components.items()},
        duration_ms=round(duration_ms, 2),
        ctx=dict(ctx),
    )


def decompose_reward(
    before: Dict,
    after: Dict,
    verdict: str,
    outcome_kind: str,
) -> Dict[str, float]:
    """Compute reward component breakdown (mirrors reward.outcome_reward terms).

    This is a pure function that returns the individual terms that sum to the
    final reward. Used to populate reward_components in DecisionTrace.
    """
    if outcome_kind == "ENV_ERROR":
        return {"env_error": 0.0}

    from reward import WEIGHTS, _safe_get

    c = WEIGHTS
    components: Dict[str, float] = {}

    # XP
    xp_delta = max(0.0, _safe_get(after, "xp") - _safe_get(before, "xp"))
    if xp_delta > 0:
        components["xp"] = round(xp_delta * c["xp"], 6)

    # Copper
    copper_delta = max(0.0, _safe_get(after, "copper") - _safe_get(before, "copper"))
    if copper_delta > 0:
        components["copper"] = round(copper_delta * c["copper"], 6)

    # Quest progress
    qp_delta = max(
        0.0,
        _safe_get(after, "quest_progress") - _safe_get(before, "quest_progress"),
    )
    if qp_delta > 0:
        components["quest_progress"] = round(qp_delta * c["quest_progress"], 6)

    # Quests done
    qd_delta = max(
        0.0,
        _safe_get(after, "quests_done") - _safe_get(before, "quests_done"),
    )
    if qd_delta > 0:
        components["quests_done"] = round(qd_delta * c["quests_done"], 6)

    # Kills
    kills_delta = max(
        0.0, _safe_get(after, "kills") - _safe_get(before, "kills")
    )
    if kills_delta > 0:
        components["kills"] = round(kills_delta * c["kills"], 6)

    # Loot items
    inv_delta = max(
        0.0,
        _safe_get(after, "inv_slots") - _safe_get(before, "inv_slots"),
    )
    if inv_delta > 0:
        components["loot_items"] = round(inv_delta * c["loot_items"], 6)

    # Death
    died = _safe_get(after, "deaths") > _safe_get(before, "deaths")
    if died:
        components["death"] = c["death"]

    # Verdict bonus/penalty
    if not died:
        if verdict == "SUCCESS":
            # Only add success_bonus if there's a world delta
            world_delta_seen = abs(sum(components.values())) > 1e-9
            if world_delta_seen:
                components["success_bonus"] = c["success_bonus"]
        elif verdict == "FAILURE":
            components["failure_penalty"] = c["failure_penalty"]

    # Drift (distance)
    if not died:
        d_before = _safe_get(before, "distance_to_giver")
        d_after = _safe_get(after, "distance_to_giver")
        if d_after < d_before:
            progress = (d_before - d_after) * c["dist_progress"]
            if abs(progress) > 1e-9:
                components["dist_progress"] = round(progress, 6)
        elif d_after > d_before:
            drift = d_after - d_before
            val = max(c["drift_cap"], drift * c["drift_per_unit"])
            if abs(val) > 1e-9:
                components["drift"] = round(val, 6)

    # Low HP penalty
    if not died:
        hp_loss = _safe_get(before, "hp_frac") - _safe_get(after, "hp_frac")
        if hp_loss > 0:
            components["low_hp"] = round(hp_loss * c["low_hp"], 6)

    return components
