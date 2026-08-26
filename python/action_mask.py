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

try:                                   # истина о порядке — у среды
    from hierarchical_env import SKILLS as SKILL_INDEX
except Exception:                      # безопасный дубль, если импорт недоступен
    SKILL_INDEX = ["farm", "loot", "accept_quest", "turn_in_quest", "sell_junk",
                   "gather", "craft", "heal", "equip", "buy",
                   "cast_frostbolt", "cast_fireball", "craft_item"]

# Навыки, которые мост исполняет НЕ через step idx, а отдельным action.
BRIDGE_ENDPOINT_SKILLS = {
    "respawn": "respawn",
    "explore": "navigate",
}

# explore всегда доступен как fallback (у него нет предусловий)
ALWAYS_AVAILABLE = ["explore"]

# Навыки, которые маскируются, но индекса в SKILLS не имеют
EXTRA_SKILLS = ["respawn"]


def maskable_skills() -> List[str]:
    """Все навыки, для которых имеет смысл считать маску."""
    return list(SKILL_INDEX) + [s for s in EXTRA_SKILLS if s not in SKILL_INDEX]


def get_action_mask(obs: Dict[str, Any]) -> List[int]:
    """Маска по порядку SKILL_INDEX: 1 = доступно, 0 = нет."""
    return [1 if check_preconditions(s, obs)["ok"] else 0 for s in SKILL_INDEX]


def available_actions(obs: Dict[str, Any]) -> List[str]:
    """Имена доступных навыков (+ explore, если больше нечего делать)."""
    out = [s for s in maskable_skills() if check_preconditions(s, obs)["ok"]]
    return out or list(ALWAYS_AVAILABLE)


def mask_candidates(cands: List[str], obs: Dict[str, Any]) -> List[str]:
    """Отфильтровать кандидатов политики по предусловиям.

    Никогда не возвращает пустой список: если всё замаскировано — explore.
    """
    ok = []
    for c in cands:
        if c in ALWAYS_AVAILABLE:
            ok.append(c)
        elif check_preconditions(c, obs)["ok"]:
            ok.append(c)
    return ok or list(ALWAYS_AVAILABLE)


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
