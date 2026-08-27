
def _gather_tool_needed(info: dict):
    """Tool id required by an active gather objective — READ FROM THE GAME.

    Canonical (2026-08-26): the tool item id must come from the snapshot
    objective itself (`toolItemId` / `requiredToolId` / `toolId`). No static
    profession->item table lives here any more: hardcoded names drifted from
    the live item list twice already.

    Invariant kept: if the tool is ALREADY in the bag we return None — that is
    an EQUIP state, not a BUY state (otherwise the policy buy-spams forever).
    """
    inv_ids = {s.get("itemId") for s in (info.get("inventory") or []) if isinstance(s, dict)}
    for q in ((info.get("quests") or {}).get("active") or []):
        for o in (q.get("objectives") or []):
            if o.get("type") != "gather":
                continue
            if (o.get("current") or 0) >= (o.get("required") or 0):
                continue
            tool = o.get("toolItemId") or o.get("requiredToolId") or o.get("toolId")
            if tool and tool not in inv_ids:
                return tool
    return None


def _objectives_view(quest: dict):
    """Objectives exactly as the game reports them (sim.questLog objectives)."""
    out = []
    for o in (quest.get("objectives") or []):
        if not isinstance(o, dict):
            continue
        out.append({
            "type": o.get("type"),
            "targetMobId": o.get("targetMobId") or o.get("mobId") or o.get("targetId"),
            "itemId": o.get("itemId"),
            "nodeType": o.get("nodeType"),
            "current": o.get("current") or 0,
            "required": o.get("required") or 0,
        })
    return out

"""world_state.py — SINGLE source of truth for the agent's WorldState.

Why this file exists (bug found 2026-08-17, measured by _diag_bucket.py):

`policy.GoalManager._world_state()` and `agent._world_state_dict()` each built
their OWN partial state dict, and BOTH were fed to `memory._bucket()`:

  decide() bucket : hp=full|qs=NONE|mob=1|corpse=1|junk=1|danger=0|far=0|combat=0
  learn()  bucket : hp=full|qs=NONE|mob=0|corpse=0|junk=0|danger=0|far=1|combat=0

The policy state had no `distance_to_giver`/`in_combat` (so `far`/`combat` were
pinned to 0), and the agent state had no `has_mob`/`has_corpse`/`has_junk`/
`danger` (so those were pinned to 0). Consequence, measured: a lesson written
with value -0.999 under the learn() key was read back as +0.000 by the decide()
key. Every lesson was filed under a bucket the decision path never looked up —
so learning COULD NOT change behaviour, and P(action|far) could never move for
the far bucket.

This also invalidates the earlier "P(return|far) 0 -> 0.15" reading: that was
measured by filtering on the observed distance, while the policy was actually
reading a far=0 bucket. The shift was a confound, not a lesson about distance.

Fix: build the FULL state once, here, and use it for candidates, bucketing and
reward. Fields are OBSERVATIONS (measured facts), never rules.
"""

from typing import Dict

# Единый junk-предикат (P0.1) — общий с observation/contracts.
from item_prices import is_junk_item as _is_junk_item


def build_world_state(info: Dict) -> Dict:
    """Flatten env info into the complete WorldState.

    Superset of what three consumers need:
      - memory._bucket(): hp_frac, quest_status, has_mob, has_corpse, has_junk,
        danger, distance_to_giver, in_combat
      - policy._candidates(): hp_frac (+ raw info for entity lists)
      - reward.outcome_reward(): xp, copper, kills, quests_done, deaths,
        inv_slots, quest_progress, distance_to_giver
    """
    p = info.get("player", {}) or {}
    hp = p.get("hp")
    maxhp = p.get("maxHp") or p.get("hpMax") or 1
    hp_frac = (hp / maxhp) if hp is not None else 1.0

    nearby = info.get("nearby") or []
    # player_class: the game's own template for the self player entity
    # (sim.entities -> kind == 'player' -> templateId). No hardcoded default.
    player_class = (info.get("player_class")
                    or p.get("templateId") or p.get("classId") or None)
    if player_class is None:
        _self_ents = [e for e in nearby
                      if isinstance(e, dict) and (e.get("kind") == "player" or e.get("type") == "player")]
        _self = next((e for e in _self_ents if e.get("self") or e.get("isSelf")), None)
        if _self is None and len(_self_ents) == 1:
            _self = _self_ents[0]
        if _self is not None:
            player_class = _self.get("templateId") or _self.get("classId") or None
    player_facing = p.get("facing") if p.get("facing") is not None else info.get("facing")
    pmax = maxhp  # player's own max HP, used to judge mob strength
    # Mob strength: a mob is "strong" if its max HP exceeds the player's by a
    # meaningful margin (can kill the player). This is an OBSERVATION the policy
    # uses to avoid suicidal farm choices — not a hard rule forbidding farm.
    STRONG_RATIO = 1.3
    strong_mob_near = False
    weak_mob_near = False
    for e in nearby:
        if (e.get("kind") == "mob" or e.get("type") == "mob") and not e.get("lootable"):
            mmax = e.get("maxHp") or 0
            if mmax > pmax * STRONG_RATIO:
                strong_mob_near = True
            elif 0 < mmax <= pmax * STRONG_RATIO:
                weak_mob_near = True
    has_mob = strong_mob_near or weak_mob_near
    has_corpse = any(
        ((e.get("type") == "corpse" or e.get("kind") == "corpse")
         or ((e.get("kind") == "mob" or e.get("type") == "mob")
             and (e.get("dead") or e.get("lootable"))))
        and not e.get("looted")
        for e in nearby
    )

    inv = info.get("inventory") or []
    # Вместимость сумок: реальная из игры (BACKPACK_SLOTS + сумки)
    bag_capacity = info.get("bagCapacity") or 16
    bag_slots_used = len([s for s in inv if s])
    bag_full = bag_slots_used >= bag_capacity
    # junk-детект (P0.1): `quality` в игре — СТРОКА ('poor'/'common'/...),
    # а не число. Прежний код сравнивал её с нулём -> `?? 0` давал фейковый
    # junk, из-за чего детект отключили целиком (has_junk = False). Вывод был
    # неверный: поле есть, оно строковое. Теперь единый предикат из
    # item_prices (факт из items.ts): junk == quality 'poor', 8 предметов.
    # quality=None -> НЕ хлам (fail-closed).
    junk_count = sum(1 for s in inv
                     if isinstance(s, dict)
                     and _is_junk_item(s.get("itemId"), s.get("quality")))
    has_junk = junk_count > 0

    # vendor proximity: is a vendor NPC within interact range? Drives sell_junk
    # candidacy in policy (no point offering sell_junk when the vendor is far,
    # since navigate_to_vendor does not exist and the bridge no-ops the call).
    ppos = info.get("player_pos") or [0, 0]
    vendor_nearby = any(
        (e.get("kind") == "npc" or e.get("type") == "npc")
        and (e.get("vendor") or e.get("vendorItems") or e.get("isVendor"))
        and ((e.get("x", 0) - ppos[0]) ** 2 + (e.get("z", 0) - ppos[1]) ** 2) ** 0.5 <= 12
        for e in nearby
    )

    # Mage/caster facts (official classes.ts: mage = mana resource, ranged kit).
    # The agent must SEE its mana and its castable abilities as NUMBERS, or it
    # melee-tanks like a warrior and never uses the kit it actually has.
    # mana_frac sentinel -1.0 = "no mana info" (non-caster / older bridge):
    # policy treats it as "cannot cast" without crashing.
    mana = p.get("mana") if p.get("mana") is not None else info.get("mana")
    max_mana = p.get("maxMana") if p.get("maxMana") is not None else info.get("maxMana")
    if isinstance(mana, (int, float)) and isinstance(max_mana, (int, float)) and max_mana > 0:
        mana_frac = round(max(0.0, min(1.0, mana / max_mana)), 4)
    else:
        mana_frac = -1.0
    abilities = []
    for a in (info.get("abilities") or []):
        if not isinstance(a, dict) or not a.get("id"):
            continue
        affordable = (mana if isinstance(mana, (int, float)) else 0) >= (a.get("cost") or 0)
        abilities.append({
            "id": a["id"],
            "name": a.get("name") or a["id"],
            "cost": a.get("cost") or 0,
            "range": a.get("range") or 0,
            "ready": bool(a.get("ready")) and affordable,
        })
    has_ready_damage_spell = any(
        a["ready"] and a["id"] in ("fireball", "frostbolt", "arcane_missiles",
                                   "fire_blast", "scorch", "ice_lance")
        for a in abilities
    )

    # Economy loop (spec 2026-08-22): inventory by item id, craftable recipes.
    inv_by_id = {}
    for it in inv:
        iid = it.get("itemId") or (it.get("def") or {}).get("id")
        if not iid:
            continue
        inv_by_id[iid] = inv_by_id.get(iid, 0) + (it.get("count") or 1)
    STATION_RANGE = 8.0
    px, pz = info.get("player_pos") or [0, 0]
    stations = info.get("stations") or []
    station_types_near = {
        s.get("stationType") for s in stations
        if s.get("stationType") and ((s.get("x", 9999) - px) ** 2 + (s.get("z", 9999) - pz) ** 2) ** 0.5 <= STATION_RANGE
    }
    craftable_now = []
    for rec in (info.get("recipes_known") or []):
        if not isinstance(rec, dict) or not rec.get("id"):
            continue
        ok_reagents = all(
            inv_by_id.get(rg.get("itemId"), 0) >= (rg.get("count") or 0)
            for rg in (rec.get("reagents") or [])
        )
        if not ok_reagents:
            continue
        st = rec.get("stationType")
        if st and st not in station_types_near:
            continue
        craftable_now.append({"id": rec["id"], "resultItemId": rec.get("resultItemId")})

    # quest facts: progress, status, and MEASURED distance to the turn-in NPC
    quest_progress = 0
    distance_to_giver = 999.0
    quest_status = "NONE"
    active = info.get("quests", {}).get("active") or []
    ready = info.get("quests", {}).get("ready") or []
    all_q = active + ready

    # Structured quest block (user 2026-08-20): the agent must SEE the real
    # phase, progress and turn-in distance as NUMBERS, not as 8-bit buckets.
    # `complete = progress >= required` (never `required == current`, which is
    # false when the bridge reports 0/0 on a freshly-accepted quest).
    quest_struct = {
        "id": None,
        "phase": "NONE",          # NONE | ACTIVE | READY
        "accepted": False,
        "progress": 0,
        "required": 0,
        "complete": False,
        "giver_id": None,
        "giver_known": False,
        "giver_distance": 999.0,
        "objectives": [],
    }
    if all_q:
        any_incomplete = False
        for q in all_q:
            for o in (q.get("objectives") or []):
                cur = o.get("current") or 0
                req = o.get("required") or 0
                quest_progress += min(cur, req)
                if cur < req:
                    any_incomplete = True
            tNpc = q.get("turnInNpc") or {}
            if tNpc.get("x") is not None:
                px, pz = info.get("player_pos", [0, 0])
                d = ((tNpc["x"] - px) ** 2 + (tNpc["z"] - pz) ** 2) ** 0.5
                # keep the CLOSEST turn-in NPC, not the last one iterated
                if d < distance_to_giver:
                    distance_to_giver = d
        # quest_status is finalized below (after the chosen quest q / qcomplete
        # are computed) so it reflects the TRUTH, not a raw incomplete-scan.

        # Выбор ОДНОГО квеста для ws.quest.
        # ИСПРАВЛЕНО 2026-08-24 (замер на живом мире): раньше брался первый
        # квест с известным гивером, а готовность не учитывалась вовсе. Из-за
        # этого при 10 активных и 1 ГОТОВОМ (q_prof_workorder_loom 6/6) выбирался
        # q_greyjaw (0/1), FSM видел phase=ACTIVE и держал DO_OBJECTIVE —
        # агент 37 шагов не шёл сдавать готовый квест, quests_turned_in=0.
        # Теперь порядок приоритета:
        #   1) ГОТОВЫЙ к сдаче с известным гивером (можно дойти и сдать),
        #   2) любой ГОТОВЫЙ (гивера дозапросим из nearby/WorldMemory),
        #   3) активный с известным гивером,
        #   4) любой активный.
        def _is_ready(cand):
            if cand.get("state") == "ready":
                return True
            objs = cand.get("objectives") or []
            return bool(objs) and all(
                (o.get("current") or 0) >= (o.get("required") or 0) for o in objs)

        def _giver_known(cand):
            return (cand.get("turnInNpc") or {}).get("x") is not None

        usable = [c for c in all_q
                  if c.get("state") in ("active", "ready", "complete")
                  or c.get("state") is None]
        q = None
        for pred in (lambda c: _is_ready(c) and _giver_known(c),
                     _is_ready,
                     _giver_known,
                     lambda c: True):
            for cand in usable:
                if pred(cand):
                    q = cand
                    break
            if q is not None:
                break
        if q is not None:
            # aggregate objective progress across all objectives of this quest
            prog = 0
            req = 0
            incomplete = False
            for o in (q.get("objectives") or []):
                cur = o.get("current") or 0
                r = o.get("required") or 0
                prog += min(cur, r)
                req += r
                if cur < r:
                    incomplete = True
            # CRITICAL: complete only when progress actually reached required,
            # AND required > 0. A quest reporting 0/0 (required==0) is NOT complete
            # — that is either a not-yet-loaded objective or a degenerate quest;
            # treating 0/0 as READY made the agent run to the giver without doing
            # anything (user: "required == current == 0 must not mean READY").
            # EXCEPTION (plan-stack fix 2026-08-25): server state=="ready" is
            # AUTHORITATIVE — the game itself says the quest is turn-in-able
            # (objectives may be empty in the snapshot after respawn). Trust it.
            qcomplete = ((bool(q.get("objectives")) and (not incomplete) and req > 0)
                         or q.get("state") == "ready")
            qphase = "READY" if qcomplete else "ACTIVE"
            # quest_status reflects the TRUTH: READY_TO_TURN_IN only when the
            # chosen quest actually reports complete (objectives present AND every
            # current >= required). A freshly-accepted quest with empty/0-0
            # objectives stays ACTIVE, never a false READY_TO_TURN_IN.
            quest_status = "READY_TO_TURN_IN" if qcomplete else "ACTIVE"
            tNpc = q.get("turnInNpc") or {}
            quest_struct = {
                "id": q.get("id") or q.get("questId"),
                "phase": qphase,
                "accepted": True,
                "progress": prog,
                "required": req,
                "complete": qcomplete,
                "giver_id": str(tNpc.get("id")) if tNpc.get("id") is not None else None,
                "giver_known": tNpc.get("x") is not None,
                "giver_distance": distance_to_giver,
                "objectives": _objectives_view(q),
            }

    in_combat = bool(info.get("in_combat"))
    dead = bool(p.get("dead"))
    danger = dead or (hp_frac < 0.3) or in_combat

    # Умная продажа: какие предметы НУЖНЫ для квестов и крафта.
    # Продавать только то, чего нет в этих множествах — иначе агент
    # продаст quest_item и не сможет сдать квест.
    quest_items_needed = set()
    craft_items_needed = set()
    for q in all_q:
        for o in (q.get("objectives") or []):
            if o.get("type") == "collect" and o.get("itemId"):
                quest_items_needed.add(o["itemId"])
    for rec in (info.get("recipes_known") or []):
        for rg in (rec.get("reagents") or []):
            if rg.get("itemId"):
                craft_items_needed.add(rg["itemId"])

    # has_ready: a turn-in-ready quest exists in the log (any). The FSM keeps a

    # ---- canonical inventory / world blocks (all values from the snapshot) ----
    inventory_block = {
        "capacity": bag_capacity,
        "used_slots": bag_slots_used,
        "free_slots": max(0, bag_capacity - bag_slots_used),
        "quest_items": {
            iid: cnt for iid, cnt in inv_by_id.items() if iid in quest_items_needed
        },
        "by_id": inv_by_id,
        # P0.1: junk считается ОДИН раз здесь; observation больше не имеет
        # своей копии логики. P0.2: equipment входит в canonical блок, иначе
        # контракт equip -> equipment_changed слеп.
        "junk_count": junk_count,
        "equipment": dict(info.get("equipment") or {}),
    }

    def _ent(e):
        return {
            "id": e.get("id"),
            "templateId": e.get("templateId"),
            "name": e.get("name"),
            "hp": e.get("hp"),
            "maxHp": e.get("maxHp"),
            "x": e.get("x"),
            "z": e.get("z"),
            "nodeType": e.get("nodeType"),
            "lootable": bool(e.get("lootable")),
            "distance": round((((e.get("x") or 0) - ppos[0]) ** 2
                               + ((e.get("z") or 0) - ppos[1]) ** 2) ** 0.5, 3),
        }

    nearby_mobs, gather_nodes, vendors = [], [], []
    for e in nearby:
        if not isinstance(e, dict):
            continue
        kind = e.get("kind") or e.get("type")
        if kind == "mob" and not e.get("lootable"):
            nearby_mobs.append(_ent(e))
        elif kind == "node":
            gather_nodes.append(_ent(e))
        elif kind == "npc" and (e.get("vendor") or e.get("vendorItems") or e.get("isVendor")):
            vendors.append(_ent(e))
    world_block = {
        "nearby_mobs": nearby_mobs,
        "gather_nodes": gather_nodes,
        "vendors": vendors,
    }

    return {
        # canonical player facts straight from sim.player / sim.entities
        "player_class": player_class,
        "player_facing": player_facing,
        "player_level": p.get("level"),
        "mana": mana,
        "max_mana": max_mana,
        "inventory": inventory_block,
        "world": world_block,
        # has_ready: a turn-in-ready quest exists (any). The FSM keeps
        # RETURN_TO_GIVER alive while this is true.
        "has_ready": bool(ready),
        # bucket features (observations)
        "hp_frac": hp_frac,
        "player_maxhp": maxhp,
        "quest_status": quest_status,
        "has_mob": has_mob,
        "strong_mob_near": strong_mob_near,
        "weak_mob_near": weak_mob_near,
        "has_corpse": has_corpse,
        "has_junk": has_junk,
        "vendor_nearby": vendor_nearby,
        "danger": danger,
        "distance_to_giver": distance_to_giver,
        "in_combat": in_combat,
        "dead": dead,
        # reward counters (deltas computed by reward.outcome_reward)
        "kills": info.get("kills", 0),
        "xp": info.get("xp", 0),
        "copper": info.get("copper", 0),
        # Честный счётчик сданных квестов (шаг 1 спеки от 2026-08-24).
        # Раньше здесь стояло только info.get('quests_done'), которое в
        # ОНЛАЙНЕ всегда было 0 (мост читал Set через typeof==='number').
        # Из-за этого дельта награды за сдачу была всегда 0, и вся история
        # обучения получала ложный сигнал «квесты сдавать бесполезно»
        # (реально сдано 7 квестов при метрике 0).
        # Теперь: берём максимум из поля снапшота и размера ведра done —
        # в онлайне истину даёт поле (online.questsDone), в офлайн-симе
        # ведро done.
        "quests_done": max(
            int(info.get("quests_done") or 0),
            len((info.get("quests") or {}).get("done") or []),
        ),
        "deaths": info.get("deaths", 0),
        "inv_slots": len(inv),
        "bag_capacity": bag_capacity,
        "bag_full": bag_full,
        "quest_progress": quest_progress,
        # structured quest view (numbers, not bits) — see task 2
        "quest": quest_struct,
        # caster view: mana + castable abilities (mage kit), see classes.ts
        "mana_frac": mana_frac,
        "abilities": abilities,
        "has_ready_damage_spell": has_ready_damage_spell,
        # economy view: inventory by id, recipes craftable right now
        "inv_by_id": inv_by_id,
        # P0.10: тот же словарь под именем, которое читают потребители
        # (policy._has_healing, observation). Мост кладёт `inventory_by_id`
        # в info; canonical ws обязан отдавать это имя тоже, иначе предикат,
        # читающий "не то" имя, становится вечным False и глушит навык —
        # ровно так heal работал только благодаря мосту.
        "inventory_by_id": inv_by_id,
        "craftable_now": craftable_now,
        # Умная продажа: какие предметы НУЖНЫ для квестов и крафта.
        # Продавать только то, чего нет в этих множествах — иначе агент
        # продаст quest_item и не сможет сдать квест.
        "quest_items_needed": quest_items_needed,
        "craft_items_needed": craft_items_needed,
        # Сбор ресурсов: id инструмента берётся ИЗ ИГРЫ (objective.toolItemId),
        # без статических таблиц профессий.
        "needs_tool": _gather_tool_needed(info) or None,
    }
