"""navigation.py — Navigation Controller (ARCHITECTURE.md §6).

Навигация отделена от high-level policy и возвращает СТАТУС, а не серию
движений:

    ARRIVED  — дошли (dist <= tolerance)
    MOVING   — приближаемся
    STUCK    — позиция не меняется
    BLOCKED  — двигаемся, но дистанция не падает (обходим препятствие)
    TIMEOUT  — бюджет шагов на цель исчерпан
    NO_TARGET— цели нет

Координаты цели берутся ИЗ ИГРЫ (сущности снапшота), не из таблиц.
"""
import math
from typing import Any, Dict, List, Optional, Tuple

ARRIVED = "ARRIVED"
MOVING = "MOVING"
STUCK = "STUCK"
BLOCKED = "BLOCKED"
TIMEOUT = "TIMEOUT"
NO_TARGET = "NO_TARGET"

# Гейты из src/sim: INTERACT_RANGE=5, accept/turn-in = INTERACT_RANGE+2
TOLERANCE = {
    "quest_giver": 6.0,     # чуть строже гейта 7, чтобы не зависать на границе
    "vendor": 10.0,         # гейт покупки 12
    "node": 4.0,            # гейт harvest 5
    "mob": 25.0,            # достаточно чтобы сагрить/кастовать
    "corpse": 4.0,
}
DEFAULT_TOLERANCE = 5.0


def tolerance_for(kind: str) -> float:
    return TOLERANCE.get(kind, DEFAULT_TOLERANCE)


def _xz(e: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    x, z = e.get("x"), e.get("z")
    if x is None or z is None:
        pos = e.get("pos") or {}
        x, z = pos.get("x"), pos.get("z")
    if x is None or z is None:
        return None
    try:
        return float(x), float(z)
    except (TypeError, ValueError):
        return None


def _matches(e: Dict[str, Any], kind: str, name_hint: str = None) -> bool:
    if kind == "quest_giver":
        return bool(e.get("questIds") or e.get("questId"))
    if kind == "vendor":
        return bool(e.get("vendorItems") or e.get("isVendor") or e.get("vendor"))
    if kind == "node":
        if name_hint:
            nt = str(e.get("nodeType") or "").lower()
            if nt and str(name_hint).lower() not in nt:
                return False
        return bool(e.get("nodeType")) or e.get("kind") == "node"
    if kind == "corpse":
        return bool(e.get("lootable")) or bool(e.get("dead"))
    if kind == "mob":
        if e.get("dead") or (e.get("hp") or 1) <= 0:
            return False
        if name_hint:
            tid = str(e.get("templateId") or e.get("mobId") or "").lower()
            if tid and str(name_hint).lower() not in tid:
                return False
        return e.get("kind") == "mob"
    return False


def find_target(obs: Dict[str, Any], kind: str,
                name_hint: str = None) -> Optional[Dict[str, Any]]:
    """Ближайшая сущность нужного типа с координатами ИЗ ИГРЫ."""
    best, bd = None, float("inf")
    for e in (obs.get("_entities") or []):
        if not isinstance(e, dict) or not _matches(e, kind, name_hint):
            continue
        pos = _xz(e)
        if pos is None:
            continue
        d = e.get("_dist")
        if d is None:
            px, pz = ((obs.get("player") or {}).get("position") or [0.0, 0.0])[:2]
            d = math.hypot(pos[0] - px, pos[1] - pz)
        if d < bd:
            bd, best = d, {"x": pos[0], "z": pos[1], "dist": float(d),
                           "kind": kind, "entity": e}
    return best


class NavigationController:
    """Держит текущую цель, историю дистанций и бюджет шагов."""

    def __init__(self, max_steps_per_target: int = 60,
                 stuck_eps: float = 0.25, no_progress_limit: int = 8):
        self.max_steps = max_steps_per_target
        self.stuck_eps = stuck_eps
        self.no_progress_limit = no_progress_limit
        self.target: Optional[Dict[str, Any]] = None
        self.kind: Optional[str] = None
        self.steps = 0
        self.dist_history: List[float] = []
        self.pos_history: List[Tuple[float, float]] = []

    # -------------------------------------------------------------- targeting
    def set_target(self, obs: Dict[str, Any], kind: str,
                   name_hint: str = None) -> Optional[Dict[str, Any]]:
        """Назначить цель. Сброс бюджета только при СМЕНЕ типа цели."""
        tgt = find_target(obs, kind, name_hint)
        if tgt is None:
            self.target, self.kind = None, kind
            return None
        if self.kind != kind:
            self.steps = 0
            self.dist_history = []
            self.pos_history = []
        self.target, self.kind = tgt, kind
        return tgt

    def clear(self) -> None:
        self.target = None
        self.kind = None
        self.steps = 0
        self.dist_history = []
        self.pos_history = []

    # ------------------------------------------------------------------ status
    def observe(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        """Обновить состояние по новому observation и вернуть статус."""
        if self.target is None or self.kind is None:
            return {"status": NO_TARGET, "distance": None, "target": None}

        player = obs.get("player") or {}
        px, pz = (player.get("position") or [0.0, 0.0])[:2]
        d = math.hypot(self.target["x"] - px, self.target["z"] - pz)

        self.steps += 1
        self.dist_history.append(d)
        self.pos_history.append((px, pz))

        tol = tolerance_for(self.kind)
        if d <= tol:
            return {"status": ARRIVED, "distance": d, "tolerance": tol,
                    "target": self.target, "steps": self.steps}

        if self.steps >= self.max_steps:
            return {"status": TIMEOUT, "distance": d, "tolerance": tol,
                    "target": self.target, "steps": self.steps}

        # STUCK: позиция практически не меняется
        if len(self.pos_history) >= 4:
            recent = self.pos_history[-4:]
            moved = max(math.hypot(a[0] - b[0], a[1] - b[1])
                        for a in recent for b in recent)
            if moved < self.stuck_eps:
                return {"status": STUCK, "distance": d, "tolerance": tol,
                        "target": self.target, "steps": self.steps,
                        "moved": moved}

        # BLOCKED: двигаемся, но НЕ становимся ближе, чем уже были.
        # Сравнение с ЛУЧШЕЙ достигнутой дистанцией, а не с одной точкой окна:
        # при ходьбе по кругу дистанция колеблется, и сравнение «хуже начала
        # окна» не срабатывало (живой случай: агент обходил гивера кольцом).
        if len(self.dist_history) > self.no_progress_limit:
            window = self.dist_history[-self.no_progress_limit:]
            best_before = min(self.dist_history[:-self.no_progress_limit])
            if min(window) >= best_before - self.stuck_eps:
                return {"status": BLOCKED, "distance": d, "tolerance": tol,
                        "target": self.target, "steps": self.steps,
                        "best_before": best_before, "best_window": min(window)}

        return {"status": MOVING, "distance": d, "tolerance": tol,
                "target": self.target, "steps": self.steps}

    # ------------------------------------------------------------------ recovery
    def recovery_for(self, status: str) -> Optional[str]:
        """Что делать при плохом статусе (имена как в recovery.py)."""
        if status == STUCK:
            return "unstuck_jump"
        if status == BLOCKED:
            return "alternate_route"
        if status == TIMEOUT:
            return "abandon_objective"
        if status == NO_TARGET:
            return "explore_town"
        return None

    def nav_command(self) -> Optional[Dict[str, Any]]:
        """Команда для моста: {'action':'navigate','x':..,'z':..}."""
        if self.target is None:
            return None
        return {"action": "navigate", "x": self.target["x"],
                "z": self.target["z"], "max_steps": 40}


# Какой тип цели нужен subgoal-у планировщика
SUBGOAL_TARGET_KIND = {
    "GO_TO_GIVER": "quest_giver",
    "RETURN_TO_GIVER": "quest_giver",
    "ACCEPT": "quest_giver",
    "TURN_IN": "quest_giver",
    "GO_TO_VENDOR": "vendor",
    "GET_TOOL": "vendor",
    "SELL": "vendor",
    "GO_TO_NODE": "node",
    "GATHER": "node",
    "FIND_MOB": "mob",
    "KILL": "mob",
    "FARM": "mob",
    "LOOT": "corpse",
}


def target_kind_for_subgoal(subgoal: Dict[str, Any]) -> Optional[str]:
    if not subgoal:
        return None
    explicit = subgoal.get("target")
    if explicit in ("quest_giver", "vendor", "node", "mob", "corpse"):
        return explicit
    return SUBGOAL_TARGET_KIND.get(subgoal.get("subgoal"))
