"""skill_contracts.py — формальные контракты навыков (ARCHITECTURE.md §3).

Каждый навык описан как:
    PRECONDITIONS  — что должно быть истинно ДО выполнения
    ACTION         — последовательность шагов
    POSTCONDITIONS — что должно измениться ПОСЛЕ (иначе FAILURE)
    FAILURE_REASONS— замкнутый список причин отказа (для Recovery Manager)

Контракт — данные, а не код. Проверка предусловий (check_preconditions)
читает ТОЛЬКО observation, никаких обращений к игре: это делает контракты
тестируемыми без запущенного моста.
"""
from typing import Dict, List, Any


class UnknownPredicate(RuntimeError):
    """Предикат объявлен в контракте, но не реализован в _pred()."""

    def __init__(self, name: str):
        super().__init__(
            "precondition %r is declared in SKILL_CONTRACTS but not implemented "
            "in skill_contracts._pred() — this is a programming error, not a "
            "runtime condition" % name)
        self.predicate = name



# ---------------------------------------------------------------- contracts

SKILL_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "buy": {
        "preconditions": ["vendor_exists", "vendor_reachable", "item_exists",
                          "money_sufficient", "bags_not_full"],
        "action": "navigate_to_vendor -> buyItem -> verify_inventory",
        "postconditions": ["inventory_changed", "copper_decreased"],
        "failure_reasons": ["no_vendor", "vendor_too_far", "no_item",
                            "no_money", "bags_full"],
    },
    "sell_junk": {
        "preconditions": ["vendor_exists", "vendor_reachable", "has_junk"],
        "action": "navigate_to_vendor -> sellAllJunk -> verify_copper",
        "postconditions": ["copper_increased"],
        "failure_reasons": ["no_vendor", "vendor_too_far", "no_junk"],
    },
    "gather": {
        "preconditions": ["node_exists", "node_reachable", "has_tool",
                          "bags_not_full"],
        "action": "navigate_to_node -> harvestNode -> wait_cast -> verify_inventory",
        "postconditions": ["inventory_changed"],
        "failure_reasons": ["no_node", "node_too_far", "no_tool", "bags_full"],
    },
    "farm": {
        "preconditions": ["mob_exists", "mob_reachable", "hp_sufficient"],
        "action": "target_mob -> approach -> attack -> verify_kill",
        "postconditions": ["kills_increased"],
        "failure_reasons": ["no_mob", "mob_too_far", "hp_too_low", "mob_too_strong"],
    },
    "loot": {
        "preconditions": ["corpse_exists", "corpse_reachable", "bags_not_full"],
        "action": "navigate_to_corpse -> interact -> verify_inventory",
        "postconditions": ["inventory_changed"],
        "failure_reasons": ["no_corpse", "corpse_too_far", "bags_full"],
    },
    "accept_quest": {
        "preconditions": ["giver_exists", "giver_reachable", "quest_available"],
        "action": "navigate_to_giver -> acceptQuest -> verify_quest_log",
        "postconditions": ["quests_active_increased"],
        "failure_reasons": ["no_giver", "giver_too_far", "no_quest_available",
                            "quest_log_full"],
    },
    "turn_in_quest": {
        "preconditions": ["quest_ready", "giver_exists", "giver_reachable"],
        "action": "navigate_to_giver -> turnInQuest -> verify_quests_done",
        "postconditions": ["quests_done_increased"],
        "failure_reasons": ["quest_not_ready", "no_giver", "giver_too_far"],
    },
    "heal": {
        "preconditions": ["hp_not_full"],
        "action": "cast_heal_or_eat -> wait -> verify_hp",
        "postconditions": ["hp_increased"],
        "failure_reasons": ["hp_full", "no_heal_available", "in_combat"],
    },
    "equip": {
        "preconditions": ["item_in_bags", "item_equippable"],
        "action": "equipItem -> verify_equipment",
        "postconditions": ["equipment_changed"],
        "failure_reasons": ["no_item", "not_equippable", "level_too_low"],
    },
    "craft": {
        "preconditions": ["recipe_known", "reagents_present", "station_reachable"],
        "action": "navigate_to_station -> craftItem -> verify_inventory",
        "postconditions": ["inventory_changed"],
        "failure_reasons": ["no_recipe", "no_reagents", "no_station", "bags_full"],
    },
    "respawn": {
        "preconditions": ["is_dead"],
        "action": "releaseSpirit -> resurrectAtSpiritHealer -> wait_alive",
        "postconditions": ["is_alive"],
        "failure_reasons": ["not_dead", "respawn_unavailable"],
    },
    "explore": {
        "preconditions": [],
        "action": "walk_forward",
        "postconditions": ["position_changed"],
        "failure_reasons": ["stuck"],
    },
}


def get_skill_contract(skill: str) -> Dict[str, Any]:
    """Контракт навыка. Пустой dict для неизвестного навыка."""
    return SKILL_CONTRACTS.get(skill, {})


def all_skills() -> List[str]:
    return list(SKILL_CONTRACTS.keys())


# ------------------------------------------------------- precondition checks

def _pred(name: str, obs: Dict[str, Any]) -> bool:
    """Один предикат предусловия, читает ТОЛЬКО observation."""
    player = obs.get("player") or {}
    world = obs.get("world") or {}
    inv = obs.get("inventory") or {}
    quest = obs.get("quest") or {}
    target = obs.get("target") or {}

    if name == "vendor_exists":
        return (world.get("vendors") or 0) > 0
    if name == "vendor_reachable":
        return (world.get("vendor_distance") or 999) <= 12.0
    if name == "item_exists":
        # FAIL-CLOSED: отсутствие информации об ассортименте != «товар есть».
        # Раньше default=True давало BUY -> гарантированный failure моста
        # и мусорный отрицательный transition в replay (аудит P0.5/P0.4).
        avail = inv.get("buy_item_available")
        if avail is None:
            return False
        return bool(avail)
    if name == "money_sufficient":
        # copper > 0 НЕ значит «хватает»: handaxe стоит 20, а на руках 14.
        # Цена берётся из живого vendor_offers, иначе из справочника
        # контента (items.ts). Неизвестная цена -> считаем недостаточно.
        copper = int(player.get("copper") or 0)
        price = inv.get("buy_item_price")
        if price is None:
            return False
        return copper >= int(price)
    if name == "bags_not_full":
        return (inv.get("free_slots") or 0) > 0
    if name == "has_junk":
        return (inv.get("junk_count") or 0) > 0
    if name == "node_exists":
        return (world.get("gather_nodes") or 0) > 0
    if name == "node_reachable":
        return (world.get("node_distance") or 999) <= 5.0
    if name == "has_tool":
        # Трёхзначно: инструмент нужен и его нет -> False; нужен и есть -> True;
        # данных об инвентаре НЕТ -> False (fail-closed). Раньше отсутствие
        # данных считалось «инструмент есть» и GATHER гарантированно падал.
        if inv.get("items") is None and inv.get("missing_tool") is None:
            return False
        return not inv.get("missing_tool")
    if name == "mob_exists":
        return (world.get("nearby_mobs") or 0) > 0
    if name == "mob_reachable":
        # Дальность боя зависит от КЛАССА (src/sim/content/classes.ts):
        # warrior бьёт вплотную (~5 yd), mage кастует до 30, hunter до 35.
        # Единый порог 45 давал ложное «моб достижим» воину при мобе в 32 yd,
        # farm возвращал NO_OP и агент топтался (живой замер 2026-08-26).
        cls = str(player.get("player_class") or "").lower()
        reach = {"warrior": 6.0, "rogue": 6.0, "mage": 30.0,
                 "hunter": 35.0, "priest": 30.0, "warlock": 30.0}.get(cls, 30.0)
        return (target.get("distance") or 999) <= reach
    if name == "hp_sufficient":
        return (player.get("hp_fraction") or 0.0) >= 0.35
    if name == "corpse_exists":
        return (world.get("corpses") or 0) > 0
    if name == "corpse_reachable":
        return (world.get("corpse_distance") or 999) <= 5.0
    if name == "giver_exists":
        return (world.get("quest_givers") or 0) > 0
    if name == "giver_reachable":
        return (quest.get("giver_distance") or 999) <= 7.0
    if name == "quest_available":
        return bool(world.get("quest_available"))
    if name == "quest_ready":
        return (quest.get("ready") or 0) > 0
    if name == "quest_log_full":
        return False
    if name == "hp_not_full":
        return (player.get("hp_fraction") or 1.0) < 1.0
    if name == "is_dead":
        return bool(player.get("dead"))
    if name == "is_alive":
        return not player.get("dead")
    if name == "item_in_bags":
        return bool(inv.get("equippable_item"))
    if name == "item_equippable":
        return bool(inv.get("equippable_item"))
    if name == "recipe_known":
        return bool(obs.get("craftable_now"))
    if name == "reagents_present":
        return bool(obs.get("craftable_now"))
    if name == "station_reachable":
        return bool(obs.get("craftable_now"))
    # НЕИЗВЕСТНЫЙ предикат — FAIL-CLOSED (аудит P0.3).
    # Раньше здесь стоял `return True`: любой предикат, добавленный в контракт
    # но не реализованный тут, молча разрешал навык. Для автономного агента
    # это худший вид ошибки — он «умеет» то, что никто не проверял.
    # Полноту гарантирует assert_predicates_implemented() на старте.
    raise UnknownPredicate(name)


def all_predicates() -> List[str]:
    """Все предусловия, упомянутые в контрактах."""
    out = set()
    for c in SKILL_CONTRACTS.values():
        out.update(c.get("preconditions") or [])
    return sorted(out)


def assert_predicates_implemented() -> None:
    """Startup-проверка: каждый предикат из контрактов реализован.

    Вызывать при старте агента. Падаем громко на старте, а не тихо
    разрешаем невалидное действие в середине автономного прогона.
    """
    probe = {"player": {}, "world": {}, "inventory": {}, "quest": {},
             "target": {}}
    missing = []
    for name in all_predicates():
        try:
            _pred(name, probe)
        except UnknownPredicate:
            missing.append(name)
        except Exception:
            pass                        # предикат есть, данных в probe нет — ок
    if missing:
        raise UnknownPredicate(", ".join(missing))


def check_preconditions(skill: str, obs: Dict[str, Any]) -> Dict[str, Any]:
    """Проверить предусловия навыка.

    Возвращает {ok: bool, failed: [названия непройденных предусловий]}.
    """
    contract = get_skill_contract(skill)
    if not contract:
        return {"ok": False, "failed": ["unknown_skill"]}
    failed = [p for p in contract["preconditions"] if not _pred(p, obs)]
    return {"ok": not failed, "failed": failed}


def verify_postconditions(skill: str, progress: Dict[str, Any]) -> Dict[str, Any]:
    """Проверить постусловия по progress-дельте (см. progress.py).

    Возвращает {result: SUCCESS|FAILURE, satisfied: [...], missing: [...]}.
    """
    contract = get_skill_contract(skill)
    if not contract:
        return {"result": "FAILURE", "satisfied": [], "missing": ["unknown_skill"]}

    checks = {
        "inventory_changed": lambda p: (p.get("inventory_delta") or 0) != 0,
        "copper_decreased": lambda p: (p.get("copper_delta") or 0) < 0,
        "copper_increased": lambda p: (p.get("copper_delta") or 0) > 0,
        "kills_increased": lambda p: (p.get("kills_delta") or 0) > 0,
        "quests_done_increased": lambda p: (p.get("quests_done_delta") or 0) > 0,
        "quests_active_increased": lambda p: (p.get("quests_active_delta") or 0) > 0,
        "hp_increased": lambda p: (p.get("hp_delta") or 0.0) > 0,
        "is_alive": lambda p: bool(p.get("became_alive")),
        "equipment_changed": lambda p: bool(p.get("equipment_changed")),
        "position_changed": lambda p: (p.get("position_delta") or 0.0) > 0.1,
    }
    satisfied, missing = [], []
    for post in contract["postconditions"]:
        fn = checks.get(post)
        if fn is None:
            continue
        (satisfied if fn(progress) else missing).append(post)
    return {
        "result": "SUCCESS" if not missing else "FAILURE",
        "satisfied": satisfied,
        "missing": missing,
    }
