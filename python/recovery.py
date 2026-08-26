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
    # Имена предусловий из skill_contracts тоже приходят сюда как причина
    # отказа (why_blocked отдаёт failed[0]). «Далеко» должно вести к
    # НАВИГАЦИИ, а не к replan: иначе агент бросает достижимую цель.
    "giver_reachable":  ["navigate_to_giver", "find_giver", "next_quest"],
    "vendor_reachable": ["navigate_to_vendor", "find_alternate_vendor"],
    "node_reachable":   ["navigate_to_node", "explore_for_node"],
    "mob_reachable":    ["approach_mob", "explore_for_mob"],
    "corpse_reachable": ["navigate_to_node", "explore_for_mob"],
    "station_reachable": ["navigate_to_station", "skip_craft"],
    # отсутствие объекта — это поиск, а не отказ
    "giver_exists":     ["find_giver", "explore_town", "next_quest"],
    "vendor_exists":    ["find_alternate_vendor", "explore_town"],
    "node_exists":      ["explore_for_node", "abandon_objective"],
    "mob_exists":       ["explore_for_mob", "next_objective"],
    "corpse_exists":    ["explore_for_mob", "next_objective"],
    "money_sufficient": ["sell_junk", "farm_for_loot", "abandon_objective"],
    "item_exists":      ["find_alternate_vendor", "abandon_objective"],
    "has_tool":         ["buy_tool", "abandon_objective"],
    "hp_sufficient":    ["retreat_and_heal"],
    "bags_not_full":    ["sell_junk", "abandon_objective"],
    "quest_ready":      ["continue_objective"],
    "is_dead":          ["continue_objective"],
    "is_alive":         ["continue_objective"],
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


# ------------------------------------------------------ исполнение (P0.6)
#
# Раньше RecoveryTracker только ВОЗВРАЩАЛ строку восстановления, а исполнял
# её кто-то другой (или никто). Ниже — явная трансляция стратегии в то, что
# агент реально делает: навык, навигацию или отказ от цели.

# recovery -> навык из SKILL_CONTRACTS
RECOVERY_SKILL: Dict[str, str] = {
    "sell_junk": "sell_junk",
    "buy_tool": "buy",
    "retreat_and_heal": "heal",
    "retreat": "heal",
    "farm_for_loot": "farm",
    "turn_in_ready_quest": "turn_in_quest",
    "finish_combat": "farm",
    "gather_reagents": "gather",
    "explore_town": "explore",
    "explore_for_node": "explore",
    "explore_for_mob": "explore",
    "unstuck_jump": "explore",
    "alternate_route": "explore",
}

# recovery -> навигация к цели данного типа
RECOVERY_NAV: Dict[str, str] = {
    "navigate_to_vendor": "vendor",
    "find_alternate_vendor": "vendor",
    "navigate_to_node": "node",
    "navigate_to_giver": "quest_giver",
    "find_giver": "quest_giver",
    "approach_mob": "mob",
    "select_weaker_target": "mob",
    "navigate_to_station": "vendor",
}

# recovery, которые меняют ЦЕЛЬ, а не исполняют действие
RECOVERY_CONTROL = {
    "abandon_objective": "abandon",
    "next_objective": "next",
    "next_quest": "next",
    "replan": "replan",
    "continue_objective": "continue",
    "skip_sell": "next",
    "skip_heal": "next",
    "skip_craft": "next",
}


def plan_recovery(recovery_action: str) -> Dict[str, Any]:
    """Во что превращается стратегия восстановления.

    Возвращает ровно один исполняемый вариант:
      {"kind": "skill",   "skill": "buy"}        -> выполнить навык
      {"kind": "navigate","target": "vendor"}    -> вести навигацию
      {"kind": "control", "op": "abandon"}       -> сменить цель
    Неизвестная стратегия -> control/replan (никогда не «ничего»).
    """
    a = str(recovery_action or "")
    if a in RECOVERY_SKILL:
        return {"kind": "skill", "skill": RECOVERY_SKILL[a], "action": a}
    if a in RECOVERY_NAV:
        return {"kind": "navigate", "target": RECOVERY_NAV[a], "action": a}
    if a in RECOVERY_CONTROL:
        return {"kind": "control", "op": RECOVERY_CONTROL[a], "action": a}
    return {"kind": "control", "op": "replan", "action": a or "unknown"}


def assert_recovery_executable() -> List[str]:
    """Каждая стратегия из всех лестниц имеет исполнение.

    Startup-проверка: молча неисполняемая ветка recovery = агент, который
    «восстанавливается» только в логе.
    """
    seen = set(DEFAULT_LADDER)
    for ladder in RECOVERY_LADDER.values():
        seen.update(ladder)
    unmapped = [a for a in sorted(seen)
                if a not in RECOVERY_SKILL
                and a not in RECOVERY_NAV
                and a not in RECOVERY_CONTROL]
    if unmapped:
        raise RuntimeError(
            "recovery actions without an implementation: %s" % ", ".join(unmapped))
    return sorted(seen)


class ObjectiveBlacklist:
    """Отказ от цели с cooldown (P0.7).

    abandon_objective раньше был просто сигналом «пусть решает policy», и
    policy спокойно выбирала ту же цель снова: failure -> abandon -> policy
    -> тот же навык -> failure. Здесь отказ реально что-то меняет: пара
    (objective, reason) блокируется на N шагов.
    """

    def __init__(self, cooldown_steps: int = 60):
        self.cooldown = cooldown_steps
        self._blocked: Dict[str, int] = {}      # key -> шаг разблокировки
        self.step_no = 0

    @staticmethod
    def _key(objective: Any, reason: str = None) -> str:
        return "%s|%s" % (objective, reason or "*")

    def tick(self) -> None:
        self.step_no += 1
        for k in [k for k, until in self._blocked.items() if until <= self.step_no]:
            del self._blocked[k]

    def abandon(self, objective: Any, reason: str = None) -> None:
        if objective is None:
            return
        self._blocked[self._key(objective, reason)] = self.step_no + self.cooldown
        # блокируем и без привязки к причине: цель недостижима как таковая
        self._blocked[self._key(objective, None)] = self.step_no + self.cooldown

    def is_blocked(self, objective: Any, reason: str = None) -> bool:
        if objective is None:
            return False
        return (self._key(objective, reason) in self._blocked
                or self._key(objective, None) in self._blocked)

    def blocked_objectives(self) -> List[str]:
        return sorted(self._blocked.keys())

    def clear(self) -> None:
        self._blocked.clear()
