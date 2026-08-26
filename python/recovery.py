"""recovery.py — Recovery Manager (ARCHITECTURE.md §7).

Ошибка ОДНОГО действия не должна ломать цикл. На каждую причину отказа
(failure_reason из skill_contracts) есть стратегия восстановления и
эскалация: retry -> alternate -> replan -> abandon.
"""
from typing import Any, Dict, List

# failure_reason -> упорядоченная лестница восстановления
RECOVERY_LADDER: Dict[str, List[str]] = {
    # экономика
    "no_vendor":        ["find_alternate_vendor", "explore_town", "abandon_objective"],
    "vendor_too_far":   ["navigate_to_vendor", "find_alternate_vendor"],
    "no_money":         ["sell_junk", "farm_for_loot", "abandon_objective"],
    "no_item":          ["find_alternate_vendor", "abandon_objective"],
    "bags_full":        ["sell_junk", "abandon_objective"],
    "no_junk":          ["skip_sell"],
    # добыча
    "no_node":          ["explore_for_node", "abandon_objective"],
    "node_too_far":     ["navigate_to_node", "explore_for_node"],
    "no_tool":          ["buy_tool", "abandon_objective"],
    # бой
    "no_mob":           ["explore_for_mob", "next_objective"],
    "mob_too_far":      ["approach_mob", "explore_for_mob"],
    "hp_too_low":       ["retreat_and_heal"],
    "mob_too_strong":   ["retreat_and_heal", "select_weaker_target"],
    # квесты
    "quest_not_ready":  ["continue_objective"],
    "no_giver":         ["find_giver", "explore_town", "next_quest"],
    "giver_too_far":    ["navigate_to_giver", "find_giver"],
    "no_quest_available": ["next_quest", "explore_town"],
    "quest_log_full":   ["turn_in_ready_quest"],
    # навигация
    "stuck":            ["alternate_route", "unstuck_jump", "abandon_objective"],
    "navigation_failure": ["alternate_route", "abandon_objective"],
    # прочее
    "hp_full":          ["skip_heal"],
    "no_heal_available": ["retreat"],
    "in_combat":        ["finish_combat"],
    "no_recipe":        ["skip_craft"],
    "no_reagents":      ["gather_reagents", "skip_craft"],
    "no_station":       ["navigate_to_station", "skip_craft"],
    "unknown_skill":    ["replan"],
}

DEFAULT_LADDER = ["replan", "abandon_objective"]


def get_recovery(failure_reason: str, obs: Dict[str, Any] = None,
                 attempt: int = 0) -> str:
    """Стратегия восстановления для причины отказа.

    attempt — номер попытки (0-based): чем выше, тем агрессивнее эскалация.
    За пределами лестницы всегда abandon_objective, чтобы цикл не завис.
    """
    ladder = RECOVERY_LADDER.get(failure_reason, DEFAULT_LADDER)
    if attempt < len(ladder):
        return ladder[attempt]
    return "abandon_objective"


def ladder_for(failure_reason: str) -> List[str]:
    return list(RECOVERY_LADDER.get(failure_reason, DEFAULT_LADDER))


class RecoveryTracker:
    """Считает попытки восстановления по (skill, failure_reason).

    Сбрасывается при первом успехе навыка — иначе агент навсегда запомнит
    отказ, случившийся один раз.
    """

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts
        self._attempts: Dict[str, int] = {}

    def _key(self, skill: str, reason: str) -> str:
        return f"{skill}:{reason}"

    def next_action(self, skill: str, failure_reason: str,
                    obs: Dict[str, Any] = None) -> Dict[str, Any]:
        key = self._key(skill, failure_reason)
        attempt = self._attempts.get(key, 0)
        action = get_recovery(failure_reason, obs, attempt)
        self._attempts[key] = attempt + 1
        return {
            "recovery_action": action,
            "attempt": attempt,
            "exhausted": attempt + 1 >= self.max_attempts,
        }

    def on_success(self, skill: str) -> None:
        prefix = f"{skill}:"
        for k in [k for k in self._attempts if k.startswith(prefix)]:
            del self._attempts[k]

    def reset(self) -> None:
        self._attempts.clear()
