"""Canonical telemetry record for every agent decision."""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

TRACE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "decision_trace.jsonl")
_TRACE_LOCK = threading.Lock()
_TRACE_FILE = None
_TRACE_PENDING = 0
_TRACE_FLUSH_EVERY = 32


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))


def _world_state_hash(ws: Dict) -> str:
    return hashlib.sha256(_canonical_json(ws).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class DecisionTrace:
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


def _close_trace_file() -> None:
    global _TRACE_FILE, _TRACE_PENDING
    with _TRACE_LOCK:
        if _TRACE_FILE is not None:
            try:
                _TRACE_FILE.flush()
                _TRACE_FILE.close()
            except Exception:
                pass
            _TRACE_FILE = None
        _TRACE_PENDING = 0


atexit.register(_close_trace_file)


def write_decision_trace(trace: DecisionTrace) -> None:
    """Append telemetry with one open handle and batched flushes.

    Flushing every record made the previous optimization retain most of the
    filesystem overhead at high headless FPS. A small batch keeps normal loss
    bounded while reducing flush syscalls by ~32x. Shutdown still flushes all
    pending records.
    """
    global _TRACE_FILE, _TRACE_PENDING
    try:
        line = json.dumps(asdict(trace), ensure_ascii=False, default=str, separators=(",", ":")) + "\n"
        with _TRACE_LOCK:
            if _TRACE_FILE is None or _TRACE_FILE.closed:
                os.makedirs(os.path.dirname(TRACE_PATH), exist_ok=True)
                _TRACE_FILE = open(TRACE_PATH, "a", encoding="utf-8", buffering=8192)
            _TRACE_FILE.write(line)
            _TRACE_PENDING += 1
            if _TRACE_PENDING >= _TRACE_FLUSH_EVERY:
                _TRACE_FILE.flush()
                _TRACE_PENDING = 0
    except Exception:
        try:
            _close_trace_file()
        except Exception:
            pass


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
    """Single factory for the canonical trace schema."""
    q = ws_before.get("quest") or {}
    objective_id = str(q["id"]) if q.get("id") else None
    if objective_id is None and ws_before.get("target_mob_id"):
        objective_id = str(ws_before["target_mob_id"])

    target_id = ws_before.get("target_mob_id")
    progress: Dict[str, float] = {}
    for key, before_key, after_key in (
        ("xp_delta", "xp", "xp"),
        ("copper_delta", "copper", "copper"),
        ("kills_delta", "kills", "kills"),
        ("deaths_delta", "deaths", "deaths"),
    ):
        before = ws_before.get(before_key, 0) or 0
        after = ws_after.get(after_key, 0) or 0
        delta = after - before
        if abs(delta) > 1e-9:
            progress[key] = round(delta, 4)

    d_before = ws_before.get("distance_to_giver")
    d_after = ws_after.get("distance_to_giver")
    if d_before is not None and d_after is not None:
        delta = d_before - d_after
        if abs(delta) > 1e-9:
            progress["dist_delta"] = round(delta, 2)

    qp_delta = (ws_after.get("quest_progress", 0) or 0) - (ws_before.get("quest_progress", 0) or 0)
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


def decompose_reward(before: Dict, after: Dict, verdict: str, outcome_kind: str) -> Dict[str, float]:
    """Compute reward components using the canonical reward weights."""
    if outcome_kind == "ENV_ERROR":
        return {"env_error": 0.0}

    from reward import WEIGHTS, _safe_get
    c = WEIGHTS
    components: Dict[str, float] = {}
    for key, before_key, after_key, weight in (
        ("xp", "xp", "xp", c["xp"]),
        ("copper", "copper", "copper", c["copper"]),
        ("quest_progress", "quest_progress", "quest_progress", c["quest_progress"]),
        ("quests_done", "quests_done", "quests_done", c["quests_done"]),
        ("kills", "kills", "kills", c["kills"]),
        ("loot_items", "inv_slots", "inv_slots", c["loot_items"]),
    ):
        delta = max(0.0, _safe_get(after, after_key) - _safe_get(before, before_key))
        if delta > 0:
            components[key] = round(delta * weight, 6)

    died = _safe_get(after, "deaths") > _safe_get(before, "deaths")
    if died:
        components["death"] = c["death"]
    elif verdict == "SUCCESS" and abs(sum(components.values())) > 1e-9:
        components["success_bonus"] = c["success_bonus"]
    elif verdict == "FAILURE":
        components["failure_penalty"] = c["failure_penalty"]

    if not died:
        before_d = _safe_get(before, "distance_to_giver")
        after_d = _safe_get(after, "distance_to_giver")
        if after_d < before_d:
            value = (before_d - after_d) * c["dist_progress"]
            if abs(value) > 1e-9:
                components["dist_progress"] = round(value, 6)
        elif after_d > before_d:
            drift = after_d - before_d
            value = max(c["drift_cap"], drift * c["drift_per_unit"])
            if abs(value) > 1e-9:
                components["drift"] = round(value, 6)

        hp_loss = _safe_get(before, "hp_frac") - _safe_get(after, "hp_frac")
        if hp_loss > 0:
            components["low_hp"] = round(hp_loss * c["low_hp"], 6)

    return components
