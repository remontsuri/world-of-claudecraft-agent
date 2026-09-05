"""action_mask.py — Action Mask (ARCHITECTURE.md §4).

available_actions(obs): если предусловия навыка не выполнены, действие
маскируется (0). Это убирает бессмысленную часть пространства действий.

Маска ВЫВОДИТСЯ из skill_contracts — один источник истины, никакого
второго набора правил, который разъедется с контрактами.

Порядок индексов — ИСТИНА ИЗ hierarchical_env.SKILLS (его же ждёт мост,
src/bridge/actions.cjs: «step idx MUST match python SKILLS order»).
Навыки вне этого списка (respawn, explore) идут своими endpoint-ами моста
(action: "respawn" / "navigate"), а не через step idx.
"""
from typing import Any, Dict, List

from skill_contracts import check_preconditions

# ЕДИНСТВЕННЫЙ источник порядка навыков — среда. Silent fallback здесь был бы
# худшим вариантом: один сдвиг (BUY -> index 9 вместо 10) превращает BUY в HEAL,
# и весь replay после этого испорчен, причём молча. Лучше не стартовать.
from hierarchical_env import SKILLS as SKILL_INDEX

# Навыки, которые мост исполняет НЕ через step idx, а отдельным action.
# /GOAL п.10 fix 2026-09-03: 'navigate' skill (added in 25236d6 + 6f8ef8e)
# routes to the SAME 'navigate' bridge action as 'explore' -- the bridge
# treats both as navigate_to_coord calls. The semantic difference is
# only in the autonomy.py caller (target coordinates).
BRIDGE_ENDPOINT_SKILLS = {
    "respawn": "respawn",
    "explore": "navigate",
    "navigate": "navigate",
}

# Навыки, которые ВСЕГДА доступны независимо от предусловий.
# explore (wander) — для NO_QUEST/FIND_GIVER когда нет цели.
# navigate (navigate_to_coord) — для DO_OBJECTIVE когда мобов в nearby нет,
# но координаты известны: идти к зоне спавна мобов, а не бродить вслепую.
# Фикс 2026-09-03 /GOAL п.10: explore как universal fallback создавал
# бесконечный INCONCLUSIVE loop. Теперь caller получает осмысленный сигнал:
# [explore] = броди, [navigate] = иди к координате, [] = ничего не делать.
ALWAYS_AVAILABLE = ["explore", "navigate", "flee"]

# Навыки, которые маскируются, но индекса в SKILLS не имеют
EXTRA_SKILLS = ["respawn", "navigate", "flee"]


def maskable_skills() -> List[str]:
    """Все навыки, для которых имеет смысл считать маску."""
    return list(SKILL_INDEX) + [s for s in EXTRA_SKILLS if s not in SKILL_INDEX]


def get_action_mask(obs: Dict[str, Any]) -> List[int]:
    """Маска по порядку SKILL_INDEX: 1 = доступно, 0 = нет."""
    return [1 if check_preconditions(s, obs)["ok"] else 0 for s in SKILL_INDEX]


def available_actions(obs: Dict[str, Any]) -> List[str]:
    """Имена доступных навыков + ALWAYS_AVAILABLE fallback.

    Фикс 2026-09-03: возвращаем и explore, и navigate как fallback.
    Caller (policy.decide) сам выбирает на основе phase:
    - NO_QUEST/FIND_GIVER -> explore (искать гивера)
    - DO_OBJECTIVE -> navigate (идти к координате моба)
    """
    out = [s for s in maskable_skills() if check_preconditions(s, obs)["ok"]]
    return out or list(ALWAYS_AVAILABLE)


def mask_candidates(cands: List[str], obs: Dict[str, Any]) -> List[str]:
    """Отфильтровать кандидатов политики по предусловиям.

    ALWAYS_AVAILABLE (explore, navigate, flee) ВСЕГДА включены — не только
    как fallback. Иначе при единственном candidate=farm и мобе в 55 yd
    (warrior reach=6 yd) агент стоит на месте: farm не может атаковать,
    а explore/navigate не предложены как альтернатива для подхода.
    """
    ok = list(ALWAYS_AVAILABLE)  # always include explore/navigate/flee
    for c in cands:
        if c not in ALWAYS_AVAILABLE and check_preconditions(c, obs)["ok"]:
            ok.append(c)
    return ok


def why_blocked(skill: str, obs: Dict[str, Any]) -> List[str]:
    """Какие предусловия не выполнены (для логов и recovery)."""
    return check_preconditions(skill, obs)["failed"]


def index_of(skill: str) -> int:
    """Индекс навыка для step, -1 если навык идёт своим endpoint-ом."""
    try:
        return list(SKILL_INDEX).index(skill)
    except ValueError:
        return -1


def endpoint_of(skill: str):
    """Имя bridge-action для навыков вне step-таблицы (иначе None)."""
    return BRIDGE_ENDPOINT_SKILLS.get(skill)
