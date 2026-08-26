"""class_config.py — конфигурация классов WoC для агента.

Источник: src/sim/content/classes.ts (game source).
Агент читает класс персонажа из игры и выбирает соответствующий навык.
"""
from typing import Dict, Any

CLASS_CONFIG: Dict[str, Dict[str, Any]] = {
    "warrior": {
        "id": "warrior",
        "name": "Warrior",
        "resource": "ranged",  # ближний бой
        "range": {
            "min": 0,
            "max": 5,  # melee range
            "speed": 1.5,
            "maxRange": 5,
            "minRange": 0,
        },
        "abilities": {
            "primary": "heroic_strike",   # основная атака в ближнем бою
            "ranged": None,               # у войдя нет дальнего атаки (только charge)
            "aoe": "thunder_clap",        # AoE по ближайшим врагам
            "gap_closer": "charge",       # рывок к врагу
            "slow": "hamstring",          # замедление (для отступления)
            "buff": "battle_shout",       # бафф атаки
            "defensive": "raised_guard",  # защита
            "execute": "execute",         # добивание
        },
        "playstyle": "melee",  # стоять вплотную, бить в упор
    },
    "mage": {
        "id": "mage",
        "name": "Mage",
        "resource": "ranged",
        "range": {
            "min": 0,
            "max": 30,
            "speed": 1.8,
            "maxRange": 30,
            "minRange": 0,
            "wand": True,
            "school": "arcane",
        },
        "abilities": {
            "primary": "fireball",        # основной нюк
            "ranged": "frostbolt",        # дальняя атака + замедление
            "aoe": None,                  # нет AoE на старте
            "gap_closer": "blink",        # отступление (телепорт назад)
            "slow": "frostbolt",          # замедление через frostbolt
            "buff": "frost_armor",        # бафф брони
            "defensive": "ice_block",     # неуязвимость
            "execute": None,
        },
        "playstyle": "ranged_kite",  # держать дистанцию 27-30yd, кайтить
    },
    "hunter": {
        "id": "hunter",
        "name": "Hunter",
        "resource": "ranged",
        "range": {
            "min": 8,     # deadzone — нельзя бить вплотную
            "max": 35,
            "speed": 2.3,
            "maxRange": 35,
            "minRange": 8,
        },
        "abilities": {
            "primary": "arcane_shot",     # основная дальняя атака
            "ranged": "aimed_shot",       # мощный выстрел
            "aoe": "volley",              # AoE залп
            "gap_closer": None,           # нет рывка вперёд
            "slow": "concussive_shot",    # замедление
            "buff": "aspect_of_the_hawk", # бафф ловкости
            "defensive": "frostjaw_trap", # ловушка (заморозка)
            "execute": None,
        },
        "playstyle": "ranged_kite",  # держать дистанцию 8-35yd, не подпускать вплотную
    },
}


def get_class_config(class_id: str) -> Dict[str, Any]:
    """Возвращает конфигурацию класса по его ID."""
    return CLASS_CONFIG.get(class_id, CLASS_CONFIG["mage"])  # fallback на мага


def get_range_for_class(class_id: str) -> Dict[str, Any]:
    """Возвращает параметры дальности для класса."""
    cfg = get_class_config(class_id)
    return cfg["range"]


def get_ability_for_class(class_id: str, ability_type: str) -> str:
    """Возвращает способность класса по типу (primary, ranged, aoe, ...)."""
    cfg = get_class_config(class_id)
    return cfg["abilities"].get(ability_type)


def get_playstyle(class_id: str) -> str:
    """Возвращает стиль игры: melee или ranged_kite."""
    cfg = get_class_config(class_id)
    return cfg.get("playstyle", "ranged_kite")
