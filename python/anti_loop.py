"""anti_loop.py — Anti-loop system (ARCHITECTURE.md §8).

Детекция циклов STATE-BASED, а не `if action == previous_action`:
цикл = повтор действия БЕЗ прогресса состояния. Одно и то же действие
с прогрессом (farm x20 с киллами) — это работа, а не цикл.
"""
from collections import deque
from typing import Any, Deque, Dict, List, Optional

# порог повторов БЕЗ прогресса (действие -> сколько терпим)
LOOP_THRESHOLDS: Dict[str, int] = {
    "buy": 3,
    "turn_in_quest": 5,
    "accept_quest": 5,
    "gather": 10,
    "farm": 20,
    "loot": 10,
    "sell_junk": 3,
    "heal": 5,
    "equip": 3,
    "craft": 3,
    "explore": 40,
}
DEFAULT_THRESHOLD = 5

# что делать при обнаруженном цикле
LOOP_RECOVERY: Dict[str, str] = {
    "buy": "cooldown_30_steps",
    "sell_junk": "cooldown_30_steps",
    "turn_in_quest": "re_evaluate_quest",
    "accept_quest": "re_evaluate_quest",
    "gather": "inspect_tool_node",
    "farm": "select_weaker_target",
    "loot": "skip_corpse",
    "heal": "skip_heal",
    "explore": "alternate_route",
}


def threshold_for(action: str) -> int:
    return LOOP_THRESHOLDS.get(action, DEFAULT_THRESHOLD)


def detect_loop(action_history: List[str],
                progress_history: Optional[List[bool]] = None) -> bool:
    """Цикл = N последних одинаковых действий БЕЗ прогресса.

    progress_history[i] — был ли прогресс на шаге i (any_progress).
    Если progress_history не передан, считаем что прогресса не было
    (обратная совместимость с чисто action-based детекцией).
    """
    if not action_history:
        return False
    last = action_history[-1]
    n = threshold_for(last)
    if len(action_history) < n:
        return False
    window = action_history[-n:]
    if any(a != last for a in window):
        return False
    if progress_history is not None:
        pwin = progress_history[-n:]
        # был хоть один прогресс в окне -> это работа, не цикл
        if any(bool(p) for p in pwin):
            return False
    return True


def get_loop_recovery(action: str) -> str:
    return LOOP_RECOVERY.get(action, "replan")


class LoopGuard:
    """Скользящее окно (action, progress) + cooldown-и по действиям."""

    def __init__(self, window: int = 40):
        self.actions: Deque[str] = deque(maxlen=window)
        self.progress: Deque[bool] = deque(maxlen=window)
        self.states: Deque[str] = deque(maxlen=window)
        self._cooldowns: Dict[str, int] = {}
        self.steps = 0

    # ---- запись наблюдений
    def observe(self, action: str, made_progress: bool,
                state_key: str = "") -> None:
        self.actions.append(action)
        self.progress.append(bool(made_progress))
        self.states.append(state_key)
        self.steps += 1
        for a in list(self._cooldowns):
            self._cooldowns[a] -= 1
            if self._cooldowns[a] <= 0:
                del self._cooldowns[a]

    # ---- запросы
    def is_looping(self) -> bool:
        return detect_loop(list(self.actions), list(self.progress))

    def stuck_in_state(self, n: int = 30) -> bool:
        """Одно и то же состояние N шагов подряд — топчемся на месте."""
        if len(self.states) < n:
            return False
        win = list(self.states)[-n:]
        return len(set(win)) == 1 and bool(win[0])

    def no_progress_steps(self) -> int:
        cnt = 0
        for p in reversed(self.progress):
            if p:
                break
            cnt += 1
        return cnt

    def blocked(self, action: str) -> bool:
        return action in self._cooldowns

    def blocked_actions(self) -> List[str]:
        return list(self._cooldowns.keys())

    # ---- реакция
    def trip(self) -> Dict[str, Any]:
        """Зафиксировать цикл: вернуть recovery и поставить cooldown."""
        if not self.actions:
            return {"looping": False}
        action = self.actions[-1]
        recovery = get_loop_recovery(action)
        if recovery == "cooldown_30_steps":
            self._cooldowns[action] = 30
        else:
            self._cooldowns[action] = 10
        return {
            "looping": True,
            "action": action,
            "recovery_action": recovery,
            "repeats": threshold_for(action),
            "no_progress_steps": self.no_progress_steps(),
        }

    def filter_candidates(self, cands: List[str]) -> List[str]:
        """Убрать действия на cooldown-е (но не оставить пустой список)."""
        out = [c for c in cands if c not in self._cooldowns]
        return out or list(cands)
