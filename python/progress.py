"""progress.py — детектор прогресса (ARCHITECTURE.md §9).

progress(obs_before, obs_after) -> дельты. Это ВАЖНЕЕ reward:
по дельтам определяется SUCCESS / FAILURE / NO_OP каждого действия.
"""
import math
from typing import Any, Dict


def _g(d: Dict[str, Any], *path, default=0):
    """Безопасно достать вложенное значение."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def detect_progress(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Дельты между двумя observation.

    Знак имеет значение: copper_delta<0 при покупке, >0 при продаже.
    """
    bx, bz = _g(before, "player", "position", default=[0.0, 0.0]) or [0.0, 0.0]
    ax, az = _g(after, "player", "position", default=[0.0, 0.0]) or [0.0, 0.0]
    pos_delta = math.hypot(ax - bx, az - bz)

    b_dist = _g(before, "navigation", "target_distance", default=999.0)
    a_dist = _g(after, "navigation", "target_distance", default=999.0)

    prog = {
        "quest_progress": (_g(after, "quest", "objective_progress")
                           - _g(before, "quest", "objective_progress")),
        "quests_done_delta": (_g(after, "quest", "done")
                              - _g(before, "quest", "done")),
        "quests_active_delta": (_g(after, "quest", "active")
                                - _g(before, "quest", "active")),
        "quests_ready_delta": (_g(after, "quest", "ready")
                               - _g(before, "quest", "ready")),
        # free_slots уменьшается когда предмет получен -> инвертируем знак
        "inventory_delta": (_g(before, "inventory", "free_slots")
                            - _g(after, "inventory", "free_slots")),
        "xp_delta": _g(after, "player", "xp") - _g(before, "player", "xp"),
        "kills_delta": _g(after, "world", "kills") - _g(before, "world", "kills"),
        "copper_delta": (_g(after, "player", "copper")
                         - _g(before, "player", "copper")),
        "hp_delta": (_g(after, "player", "hp_fraction", default=0.0)
                     - _g(before, "player", "hp_fraction", default=0.0)),
        "level_delta": _g(after, "player", "level") - _g(before, "player", "level"),
        "deaths_delta": _g(after, "player", "deaths") - _g(before, "player", "deaths"),
        # положительное = приблизились к цели
        "distance_delta": b_dist - a_dist,
        "position_delta": pos_delta,
        "equipment_changed": (_g(after, "inventory", "equipment_rev")
                              != _g(before, "inventory", "equipment_rev")),
    }
    prog["any_progress"] = any(
        (v > 0 if isinstance(v, (int, float)) else bool(v))
        for k, v in prog.items()
        if k in ("quest_progress", "quests_done_delta", "inventory_delta",
                 "xp_delta", "kills_delta", "level_delta", "distance_delta",
                 "equipment_changed")
    )
    return prog


def classify_outcome(progress: Dict[str, Any]) -> str:
    """SUCCESS / FAILURE / NO_OP по дельтам.

    NO_OP — действие выполнилось, но мир не изменился (это НЕ успех).
    FAILURE — стало хуже (смерть).
    """
    if (progress.get("deaths_delta") or 0) > 0:
        return "FAILURE"
    if progress.get("any_progress"):
        return "SUCCESS"
    # продажа: copper вырос, инвентарь освободился
    if (progress.get("copper_delta") or 0) > 0:
        return "SUCCESS"
    if (progress.get("hp_delta") or 0.0) > 0.01:
        return "SUCCESS"
    return "NO_OP"
