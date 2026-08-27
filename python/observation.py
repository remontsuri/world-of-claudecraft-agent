"""observation.py — Observation Encoder (ARCHITECTURE.md §2).

WorldState -> observation, достаточное для ПРИНЯТИЯ РЕШЕНИЯ.
High-level policy не должна видеть только level/xp/kills/copper: ей нужен
контекст текущей задачи (какая цель, что мешает, как далеко).

Блоки: PLAYER / TARGET / QUEST / INVENTORY / WORLD / NAVIGATION.
Encoder толерантен к схеме: читает и canonical ws, и плоский info,
чтобы не ломаться пока world_state дорабатывается.
"""
import math
from typing import Any, Dict, List, Optional

# Единый junk-предикат (P0.1). Живёт в item_prices, потому что quality —
# факт контента из items.ts, а не состояние мира. Один источник для
# observation / world_state / contracts, чтобы слои не разъехались снова.
from item_prices import is_junk_item as _is_junk_item

# Дистанции-гейты из игры (src/sim): INTERACT_RANGE=5, accept/turn-in = +2
INTERACT_RANGE = 5.0
QUEST_RANGE = 7.0
VENDOR_RANGE = 12.0
MOB_SCAN_RANGE = 45.0

# Из какого блока ws["world"] какой kind восстанавливать (см. _entities).
_KIND_BY_WORLD_KEY = {
    "nearby_mobs": "mob",
    "corpses": "mob",
    "gather_nodes": "node",
    "vendors": "npc",
    "quest_givers": "npc",
    "npcs": "npc",
}


def _num(v, default=0.0) -> float:
    try:
        if v is None:
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _dist_of(e: Dict[str, Any], px: float, pz: float) -> float:
    """Дистанция сущности: берём готовую, иначе считаем от игрока."""
    d = e.get("dist")
    if d is not None:
        return _num(d, 999.0)
    x, z = e.get("x"), e.get("z")
    if x is None or z is None:
        pos = e.get("pos") or {}
        x, z = pos.get("x"), pos.get("z")
    if x is None or z is None:
        return 999.0
    return math.hypot(_num(x) - px, _num(z) - pz)


def _bearing_of(e: Dict[str, Any], px: float, pz: float) -> float:
    x, z = e.get("x"), e.get("z")
    if x is None or z is None:
        pos = e.get("pos") or {}
        x, z = pos.get("x"), pos.get("z")
    if x is None or z is None:
        return 0.0
    return math.atan2(_num(x) - px, _num(z) - pz)


def _is_kind(e: Dict[str, Any], kind: str) -> bool:
    return (e.get("kind") == kind) or (e.get("type") == kind)


def _entities(ws: Dict[str, Any], info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Сущности рядом. Порядок источников: сырой список -> canonical ws.world.

    Раньше здесь были только ws["nearby"] / info["nearby"] / ws["entities"],
    поэтому при неполном raw info сущности исчезали целиком: мобы, трупы,
    узлы, вендоры и гиверы становились нулём, и farm/loot/gather/buy/
    accept_quest молча блокировались. Canonical WorldState несёт те же
    сущности в ws["world"], и adapter обязан их видеть — иначе факт живёт
    только благодаря мосту (та же поломка, что дала мёртвый heal).
    """
    for src in (ws.get("nearby"), info.get("nearby"), ws.get("entities")):
        if isinstance(src, list) and src:
            return src
    # canonical fallback: собираем обратно из ws["world"] блоков
    world = ws.get("world")
    if isinstance(world, dict):
        merged: List[Dict[str, Any]] = []
        for key in ("nearby_mobs", "corpses", "gather_nodes", "vendors",
                    "quest_givers", "npcs"):
            part = world.get(key)
            if not isinstance(part, list):
                continue
            for e in part:
                if not isinstance(e, dict):
                    continue
                # ws["world"] блоки уже разложены по типу, а kind в них может
                # отсутствовать — восстанавливаем его из имени блока, иначе
                # классификация ниже отправит всё в "прочее".
                if not e.get("kind") and not e.get("type"):
                    e = dict(e, kind=_KIND_BY_WORLD_KEY.get(key, "npc"))
                merged.append(e)
        if merged:
            return merged
    return []


def _player_pos(ws: Dict[str, Any], info: Dict[str, Any]):
    for src in (ws.get("player_pos"), info.get("player_pos")):
        if isinstance(src, (list, tuple)) and len(src) >= 2:
            return _num(src[0]), _num(src[1])
    p = ws.get("player") or info.get("player") or {}
    pos = p.get("pos") or {}
    return _num(pos.get("x")), _num(pos.get("z"))


def _quest_lists(ws: Dict[str, Any], info: Dict[str, Any]):
    q = ws.get("quests") or info.get("quests") or {}
    active = q.get("active") or []
    ready = q.get("ready") or []
    done = q.get("done") or []
    # P0.11: canonical ws не держит списков — он несёт ОДИН активный квест
    # как ws["quest"] (id/phase/objectives/giver_distance). Раньше читался
    # только ws["quests"], поэтому без raw info next_objective становился
    # None: planner терял цель и агент перестал бы доводить квесты на любом
    # пути без мостового info.
    if not active:
        cq = ws.get("quest")
        if isinstance(cq, dict) and cq.get("id"):
            active = [{
                "id": cq.get("id"),
                "state": "ready" if cq.get("complete") else "active",
                "complete": bool(cq.get("complete")),
                "objectives": cq.get("objectives") or [],
                "turnInNpc": cq.get("turnInNpc"),
                "giver_distance": cq.get("giver_distance"),
            }]
    # сервер может держать READY внутри active (state == 'ready')
    if not ready and active:
        ready = [x for x in active
                 if (x.get("state") or x.get("status")) == "ready"
                 or x.get("complete") is True]
    return active, ready, done


def _next_objective(active: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Первая НЕЗАВЕРШЁННАЯ цель первого активного квеста."""
    for q in active:
        for o in (q.get("objectives") or []):
            cur = _num(o.get("current"))
            req = _num(o.get("required"), 1.0)
            if cur < req:
                return {
                    "quest_id": q.get("id"),
                    "type": o.get("type"),
                    "item_id": o.get("itemId"),
                    "node_type": o.get("nodeType"),
                    "target_mob_id": o.get("targetMobId"),
                    "current": int(cur),
                    "required": int(req),
                    "remaining": int(max(0.0, req - cur)),
                }
    return None


# --------------------------------------------------------- покупки (P0.4)

def _buy_target(ws, info):
    """Что агент собирается купить: нужный инструмент, иначе явная цель."""
    return (ws.get("needs_tool") or ws.get("buy_item_id")
            or (info or {}).get("buy_item_id"))


def _buy_price(ws, info):
    """Цена цели покупки. None = НЕИЗВЕСТНО (fail-closed у контракта)."""
    item = _buy_target(ws, info)
    if not item:
        return None
    try:
        from item_prices import resolve_price
        return resolve_price(info or {}, item)
    except Exception:
        return None


def _buy_available(ws, info):
    """Продаёт ли ближайший вендор эту вещь. None = НЕИЗВЕСТНО."""
    item = _buy_target(ws, info)
    if not item:
        return None
    try:
        from item_prices import vendor_sells
        return vendor_sells(info or {}, item)
    except Exception:
        return None


def _quest_available_from_states(ws, givers):
    """FIX #1 (2026-08-27): quest_available = существует гивер AND
    questState(questId) == 'available'.

    Раньше было bool(givers), что означало "NPC имеет questIds", а не
    "quest сейчас available". Источник истины — sim.questState() через
    snapshot.quest_states (авторитетный метод в offline, проверен 2026-08-27).

    Args:
        ws: world state (snapshot)
        givers: список гиверов с полем 'questIds'

    Returns:
        True если хотя бы один гивер имеет quest в state == 'available'
    """
    if not givers:
        return False
    states = ws.get("quest_states") or {}
    for g in givers:
        for qid in (g.get("quest_ids") or g.get("questIds") or []):
            if states.get(qid) == "available":
                return True
    return False


# ------------------------------------------------- выбор цели боя (P0.5)

def _mob_matches(mob, mob_id):
    """Совпадает ли моб с id квестовой цели.

    В снапшоте id бывает и templateId ('forest_wolf'), и человекочитаемым
    name ('Forest Wolf') — сравниваем нормализованно.
    """
    if not mob or not mob_id:
        return False
    want = str(mob_id).lower().replace("_", " ").strip()
    if not want:
        return False
    have = " ".join(str(mob.get(k) or "") for k in
                    ("templateId", "mobId", "name")).lower().replace("_", " ")
    return want in have


def _quest_target_mob_id(ws, info):
    """id моба, который нужен активному kill-объективу (из игры)."""
    for src in (ws or {}, info or {}):
        objs = src.get("quest_objectives") or src.get("objectives")
        if isinstance(objs, list):
            for o in objs:
                if not isinstance(o, dict):
                    continue
                if (o.get("type") or "").lower() != "kill":
                    continue
                if (o.get("remaining") is not None and o.get("remaining") <= 0):
                    continue
                mid = o.get("targetMobId") or o.get("target_mob_id")
                if mid:
                    return mid
    return None


def _pick_target(mobs, quest_mob_id):
    """Квестовый моб приоритетнее ближайшего; среди квестовых — ближайший.

    Не полагаемся на предсортировку входа: полагаться на неё значило бы
    «побежать к дальнему квестовому мобу, когда рядом есть такой же».
    """
    if not mobs:
        return None
    by_dist = sorted(mobs, key=lambda m: (m.get("_dist") if m.get("_dist")
                                          is not None else m.get("dist") or 1e9))
    if quest_mob_id:
        for m in by_dist:
            if _mob_matches(m, quest_mob_id):
                return m
    return by_dist[0]


def encode_observation(ws: Dict[str, Any],
                       info: Dict[str, Any] = None) -> Dict[str, Any]:
    """Собрать observation из WorldState (+ сырой info как fallback)."""
    ws = ws or {}
    info = info or {}
    player = ws.get("player") or info.get("player") or {}
    px, pz = _player_pos(ws, info)
    ents = _entities(ws, info)

    hp = _num(player.get("hp"))
    max_hp = _num(player.get("maxHp"), 1.0) or 1.0
    hp_frac = ws.get("hp_frac")
    hp_frac = _num(hp_frac, hp / max_hp) if hp_frac is not None else hp / max_hp

    mana = _num(player.get("mana"))
    max_mana = _num(player.get("maxMana"), 0.0)
    # P0.11: мана и уровень приходят из игры ПЛОСКИМИ ключами (ws.mana,
    # ws.max_mana, ws.player_level, info.mana/maxMana) и в player-dict их нет.
    # Раньше читался только player.*, поэтому мана обнулялась, а уровень
    # сбрасывался в 1 -> классовые спеллы мага теряли ресурс, а level_diff
    # врал. Порядок: вложенное поле -> canonical ws -> raw info.
    if not mana:
        mana = _num(ws.get("mana"), _num(info.get("mana")))
    if not max_mana:
        max_mana = _num(ws.get("max_mana"), _num(info.get("maxMana")))

    # --- сущности по типам
    mobs, npcs, nodes, corpses, vendors, givers = [], [], [], [], [], []
    for e in ents:
        d = _dist_of(e, px, pz)
        rec = dict(e)
        rec["_dist"] = d
        if _is_kind(e, "mob") and not e.get("dead") and _num(e.get("hp"), 1.0) > 0:
            mobs.append(rec)
        elif (_is_kind(e, "corpse")
              or (_is_kind(e, "mob") and (e.get("dead") or e.get("lootable")))):
            # Труп = мёртвый МОБ (или явный corpse). Раньше сюда попадал любой
            # объект с lootable/dead, а в этой игре lootable стоит и у декораций
            # мира (Ogre War Totem, Grave of..., Warded Shore-Rock — живой
            # замер), из-за чего world.corpses всегда >0 и loot зациклился.
            corpses.append(rec)
        elif _is_kind(e, "npc"):
            npcs.append(rec)
            if e.get("vendorItems") or e.get("isVendor") or e.get("vendor"):
                vendors.append(rec)
            if e.get("questIds") or e.get("questId"):
                givers.append(rec)
        elif _is_kind(e, "node") or e.get("nodeType"):
            nodes.append(rec)

    mobs.sort(key=lambda r: r["_dist"])
    nodes.sort(key=lambda r: r["_dist"])
    corpses.sort(key=lambda r: r["_dist"])
    vendors.sort(key=lambda r: r["_dist"])
    givers.sort(key=lambda r: r["_dist"])

    # ЦЕЛЬ выбирается ПОСЛЕ расчёта объектива (см. ниже, после _next_objective):
    # квестовый моб приоритетнее ближайшего (P0.5).
    p_level = _num(player.get("level"), 0.0)
    if not p_level:
        # canonical ws несёт уровень как player_level (плоский ключ)
        p_level = _num(ws.get("player_level"), _num(info.get("level"), 1.0))

    active, ready, done = _quest_lists(ws, info)
    nxt = _next_objective(active)

    # Выбор цели боя: квестовый моб приоритетнее ближайшего (P0.5).
    # Раньше стояло target = mobs[0]: при квесте «убей волка», кабане в 4 yd
    # и волке в 12 yd observation указывал на кабана, а planner — на волка.
    # Политика била не того моба: прогресс квеста не шёл, но обучение
    # получало положительный сигнал за kills.
    quest_mob = (nxt or {}).get("target_mob_id") if (
        (nxt or {}).get("type") == "kill") else None
    target = _pick_target(mobs, quest_mob)
    target_is_quest = bool(target) and _mob_matches(target, quest_mob)

    # junk-детект (P0.1): считается ОДИН раз в world_state (canonical
    # inventory.junk_count) — здесь только читаем. Fallback на info оставлен
    # для вызовов с неполным ws (тесты/legacy), но логика junk одна и та же:
    # item_prices.is_junk_item, quality — строка 'poor', не число.
    # ВНИМАНИЕ: ws["inventory"] у legacy-вызовов бывает LIST — отсюда
    # isinstance-проверки, а не прямой .get().
    _inv_raw = ws.get("inventory")
    _inv_block = _inv_raw if isinstance(_inv_raw, dict) else None
    inv_list = info.get("inventory")
    if not isinstance(inv_list, list):
        inv_list = _inv_raw if isinstance(_inv_raw, list) else []

    if _inv_block is not None and _inv_block.get("junk_count") is not None:
        junk = int(_inv_block.get("junk_count") or 0)
    else:
        junk = sum(1 for it in inv_list
                   if isinstance(it, dict)
                   and _is_junk_item(it.get("itemId"), it.get("quality")))

    free_slots = ws.get("bag_free_slots")
    if free_slots is None:
        if _inv_block is not None and _inv_block.get("free_slots") is not None:
            free_slots = _num(_inv_block.get("free_slots"), 0.0)
        else:
            cap = _num(ws.get("bag_capacity"), 0.0)
            used = float(len(inv_list))
            free_slots = max(0.0, cap - used) if cap else 0.0

    obs = {
        "player": {
            "hp": hp,
            "max_hp": max_hp,
            "hp_fraction": round(hp_frac, 4),
            "mana": mana,
            "max_mana": max_mana,
            "mana_fraction": round(mana / max_mana, 4) if max_mana else 0.0,
            "level": int(p_level),
            "xp": _num(ws.get("xp", info.get("xp"))),
            "copper": _num(ws.get("copper", info.get("copper"))),
            "position": [px, pz],
            "facing": _num(player.get("facing", ws.get("player_facing"))),
            "deaths": _num(ws.get("deaths", info.get("deaths"))),
            "player_class": (ws.get("player_class")
                             or info.get("player_class") or "unknown"),
            "in_combat": bool(ws.get("in_combat", info.get("in_combat"))),
            "dead": bool(player.get("dead")),
        },
        "target": {
            "exists": target is not None,
            "hostile": bool(target) and not target.get("friendly"),
            "distance": round(target["_dist"], 2) if target else 999.0,
            "bearing": round(_bearing_of(target, px, pz), 4) if target else 0.0,
            "hp": _num(target.get("hp")) if target else 0.0,
            "level_diff": (_num(target.get("level"), p_level) - p_level) if target else 0.0,
            "mob_id": (target.get("templateId") or target.get("mobId")) if target else None,
            "in_melee_range": bool(target) and target["_dist"] <= INTERACT_RANGE,
            # цель выбрана ПО КВЕСТУ, а не просто ближайшая
            "is_quest_target": target_is_quest,
            "quest_mob_id": quest_mob,
        },
        "quest": {
            "active": len(active),
            "ready": len(ready),
            "done": len(done) if isinstance(done, list) else int(_num(done)),
            "objective_type": (nxt or {}).get("type"),
            "objective_progress": (nxt or {}).get("current", 0),
            "objective_required": (nxt or {}).get("required", 0),
            "remaining": (nxt or {}).get("remaining", 0),
            "giver_distance": round(givers[0]["_dist"], 2) if givers else 999.0,
            "next_objective": nxt,
        },
        "inventory": {
            "free_slots": int(_num(free_slots)),
            "used_slots": (_inv_block.get("used_slots")
                           if _inv_block is not None
                           and _inv_block.get("used_slots") is not None
                           else len(inv_list)),
            "junk_count": junk,
            "missing_tool": ws.get("needs_tool"),
            "quest_items": ws.get("quest_items") or [],
            "equippable_item": ws.get("equippable_item"),
            # CANONICAL из игры: {itemId: count} и {slot: itemId}.
            # По ним детектор прогресса считает реальные дельты вместо
            # слепых free_slots / отсутствующего equipment_rev (P0.1, P0.2).
            "items": (info.get("inventory_by_id")
                      or ws.get("inventory_by_id") or {}),
            "equipment": (info.get("equipment")
                          or (_inv_block or {}).get("equipment")
                          or ws.get("equipment") or {}),
            # Что именно агент собирается купить, его ЦЕНА и наличие у вендора.
            # money_sufficient сравнивает copper >= price, а не copper > 0
            # (handaxe стоит 20 при 14 на руках -> покупка была обречена).
            # None означает НЕИЗВЕСТНО и трактуется fail-closed.
            "buy_item_id": _buy_target(ws, info),
            "buy_item_price": _buy_price(ws, info),
            "buy_item_available": _buy_available(ws, info),
        },
        "world": {
            "nearby_mobs": len(mobs),
            "gather_nodes": len(nodes),
            "vendors": len(vendors),
            "npcs": len(npcs),
            "corpses": len(corpses),
            "quest_givers": len(givers),
            "vendor_distance": round(vendors[0]["_dist"], 2) if vendors else 999.0,
            "node_distance": round(nodes[0]["_dist"], 2) if nodes else 999.0,
            "corpse_distance": round(corpses[0]["_dist"], 2) if corpses else 999.0,
            "kills": _num(ws.get("kills", info.get("kills"))),
            # FIX #1 (2026-08-27): quest_available = существует гивер AND
            # questState(questId) == 'available'. Раньше было bool(givers),
            # что означало "NPC имеет questIds", а не "quest сейчас available".
            # Источник истины — sim.questState() через snapshot.quest_states.
            "quest_available": _quest_available_from_states(ws, givers),
        },
        "navigation": {
            "target_distance": round(target["_dist"], 2) if target else 999.0,
            "bearing": round(_bearing_of(target, px, pz), 4) if target else 0.0,
            "stuck": bool(ws.get("stuck")),
            "cell": ws.get("cell"),
        },
        "craftable_now": ws.get("craftable_now"),
        # сырые сущности с посчитанной дистанцией — чтобы навигация брала
        # КООРДИНАТЫ ИЗ ИГРЫ, а не из статических таблиц
        "_entities": (mobs + npcs + nodes + corpses),
        # P0-A: Canonical NPC registry
        "npc_registry": ws.get("npc_registry"),
    }
    return obs
