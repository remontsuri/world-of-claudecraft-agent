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


def _item_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, int]:
    """Дельта инвентаря по КОНКРЕТНЫМ предметам: {itemId: ±count}.

    free_slots слепы к стакам: handaxe x1 -> x2 не меняет число слотов,
    и реальная покупка/сбор классифицировались как NO_OP, а обучение
    получало сигнал, обратный действительности (аудит P0.1).
    """
    b = _g(before, "inventory", "items", default={}) or {}
    a = _g(after, "inventory", "items", default={}) or {}
    if not isinstance(b, dict) or not isinstance(a, dict):
        return {}
    out = {}
    for k in set(b) | set(a):
        d = int(a.get(k, 0) or 0) - int(b.get(k, 0) or 0)
        if d:
            out[k] = d
    return out


def _equipment_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Дельта экипировки по слотам: {slot: (было, стало)}.

    Раньше сравнивался equipment_rev, которого observation не формировал,
    поэтому контракт equip -> equipment_changed был слепым (аудит P0.2).
    """
    b = _g(before, "inventory", "equipment", default={}) or {}
    a = _g(after, "inventory", "equipment", default={}) or {}
    if not isinstance(b, dict) or not isinstance(a, dict):
        return {}
    out = {}
    for k in set(b) | set(a):
        if b.get(k) != a.get(k):
            out[k] = (b.get(k), a.get(k))
    return out


def detect_progress(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Дельты между двумя observation.

    Знак имеет значение: copper_delta<0 при покупке, >0 при продаже.
    """
    bx, bz = _g(before, "player", "position", default=[0.0, 0.0]) or [0.0, 0.0]
    ax, az = _g(after, "player", "position", default=[0.0, 0.0]) or [0.0, 0.0]
    pos_delta = math.hypot(ax - bx, az - bz)

    b_dist = _g(before, "navigation", "target_distance", default=999.0)
    a_dist = _g(after, "navigation", "target_distance", default=999.0)

    items_delta = _item_diff(before, after)
    eq_delta = _equipment_diff(before, after)
    gained = sum(v for v in items_delta.values() if v > 0)
    lost = -sum(v for v in items_delta.values() if v < 0)

    prog = {
        "quest_progress": (_g(after, "quest", "objective_progress")
                           - _g(before, "quest", "objective_progress")),
        "quests_done_delta": (_g(after, "quest", "done")
                              - _g(before, "quest", "done")),
        "quests_active_delta": (_g(after, "quest", "active")
                                - _g(before, "quest", "active")),
        "quests_ready_delta": (_g(after, "quest", "ready")
                               - _g(before, "quest", "ready")),
        # CANONICAL: дельта по предметам, а не по свободным слотам
        "items_delta": items_delta,
        "items_gained": gained,
        "items_lost": lost,
        "inventory_delta": gained - lost,
        # слоты оставляем как отдельную метрику (для bag-менеджмента)
        "free_slots_delta": (_g(after, "inventory", "free_slots")
                             - _g(before, "inventory", "free_slots")),
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
        "equipment_delta": eq_delta,
        "equipment_changed": bool(eq_delta),
        "became_alive": (bool(_g(before, "player", "dead", default=False))
                         and not bool(_g(after, "player", "dead", default=False))),
    }
    prog["any_progress"] = any(
        (v > 0 if isinstance(v, (int, float)) else bool(v))
        for k, v in prog.items()
        if k in ("quest_progress", "quests_done_delta", "inventory_delta",
                 "xp_delta", "kills_delta", "level_delta", "distance_delta",
                 "equipment_changed", "became_alive")
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
