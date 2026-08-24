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
        (e.get("type") == "corpse" or e.get("kind") == "corpse" or e.get("lootable"))
        and not e.get("looted")
        for e in nearby
    )

    inv = info.get("inventory") or []
    has_junk = any((i.get("quality") or 0) == 0 for i in inv)

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
    mana = info.get("mana")
    max_mana = info.get("maxMana")
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
            qcomplete = bool(q.get("objectives")) and (not incomplete) and req > 0
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
            }

    in_combat = bool(info.get("in_combat"))
    dead = bool(p.get("dead"))
    danger = dead or (hp_frac < 0.3) or in_combat

    # has_ready: a turn-in-ready quest exists in the log (any). The FSM keeps a

    return {
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
        "quests_done": info.get("quests_done", 0),
        "deaths": info.get("deaths", 0),
        "inv_slots": len(inv),
        "quest_progress": quest_progress,
        # structured quest view (numbers, not bits) — see task 2
        "quest": quest_struct,
        # caster view: mana + castable abilities (mage kit), see classes.ts
        "mana_frac": mana_frac,
        "abilities": abilities,
        "has_ready_damage_spell": has_ready_damage_spell,
        # economy view: inventory by id, recipes craftable right now
        "inv_by_id": inv_by_id,
        "craftable_now": craftable_now,
    }
