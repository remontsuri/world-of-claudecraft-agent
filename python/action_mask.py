"""action_mask.py — Action Mask (ARCHITECTURE.md §4).

available_actions(obs) до обучения: если предусловия навыка не выполнены,
действие маскируется (0). Это убирает бессмысленную часть пространства
действий и ускоряет обучение.

Маска ВЫВОДИТСЯ из skill_contracts — один источник истины, никакого
второго набора правил, который разъедется с контрактами.
"""
from typing import Any, Dict, List

from skill_contracts import check_preconditions

# Порядок обязан совпадать с индексами моста (browser_bridge*.cjs applyAction)
SKILL_INDEX: List[str] = [
    "farm",            # 0
    "loot",            # 1
    "accept_quest",    # 2
    "turn_in_quest",   # 3
    "sell_junk",       # 4
    "gather",          # 5
    "craft",           # 6
    "heal",            # 7
    "equip",           # 8
    "buy",             # 9
]

# explore не имеет индекса в мосте — доступен всегда как fallback
ALWAYS_AVAILABLE = ["explore"]


def get_action_mask(obs: Dict[str, Any]) -> List[int]:
    """Список из len(SKILL_INDEX) элементов: 1 = доступно, 0 = нет."""
    mask = []
    for skill in SKILL_INDEX:
        res = check_preconditions(skill, obs)
        mask.append(1 if res["ok"] else 0)
    return mask


def available_actions(obs: Dict[str, Any]) -> List[str]:
    """Имена доступных навыков (+ explore, если больше нечего делать)."""
    mask = get_action_mask(obs)
    out = [SKILL_INDEX[i] for i, m in enumerate(mask) if m]
    if not out:
        out = list(ALWAYS_AVAILABLE)
    return out


def mask_candidates(cands: List[str], obs: Dict[str, Any]) -> List[str]:
    """Отфильтровать список кандидатов политики по предусловиям.

    Никогда не возвращает пустой список: если всё замаскировано — explore.
    """
    ok = []
    for c in cands:
        if c in ALWAYS_AVAILABLE:
            ok.append(c)
            continue
        if check_preconditions(c, obs)["ok"]:
            ok.append(c)
    return ok or list(ALWAYS_AVAILABLE)


def why_blocked(skill: str, obs: Dict[str, Any]) -> List[str]:
    """Какие именно предусловия не выполнены (для логов и recovery)."""
    return check_preconditions(skill, obs)["failed"]


def index_of(skill: str) -> int:
    """Индекс навыка для моста, -1 если навык не отправляется в мост."""
    try:
        return SKILL_INDEX.index(skill)
    except ValueError:
        return -1
