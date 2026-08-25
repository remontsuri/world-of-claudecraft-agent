"""GoalManager / High-Level Policy — the agent's decision maker.

Per user 2026-08-16: this must NOT be a scripted `if HP<30: heal` bot. It is a
tabular policy whose action weights are learned from experience (see memory.py).
It CAN make mistakes (e.g. pick farm at low HP) — that's how it learns. The
verifier/outcome loop feeds reward back into memory, and bad choices become less
likely over time WITHOUT any hard-coded safety rule.

Decision flow each step:
  1. Build the candidate skill set from CURRENT world state (what's reachable).
  2. Read learned values (state_bucket, action) from ExperienceStore.
  3. Sample an action ~softmax(weights) over candidates (exploration preserved).
  4. Return (skill_name, ctx) — the Skill Library executes it.

Skills are the SAME fixed list as hierarchical_env.SKILLS (farm/loot/accept/
turn_in/heal/...). QuestSkill is just another candidate once a quest is active.

No orchestration: the policy never says "do objective then return to NPC". It only
expresses a preference. The QuestSkill itself uses QuestCapability and returns
SUCCESS/PARTIAL/FAILURE; the policy reacts to that next step.
"""

import math
import os
import random
from typing import Dict, List, Optional, Tuple

from memory import ExperienceStore, _bucket
from world_state import build_world_state

# Skill names (must align with hierarchical_env.SKILLS indices)
SKILL_FARM = "farm"
SKILL_LOOT = "loot"
SKILL_ACCEPT = "accept_quest"
SKILL_TURN_IN = "turn_in_quest"
SKILL_RETURN = "return_to_giver"
SKILL_HEAL = "heal"
SKILL_SELL = "sell_junk"
SKILL_GATHER = "gather"
SKILL_EQUIP = "equip"      # unequipped gear item in bag -> bridge equipItem
SKILL_BUY = "buy"          # vendor NPC in range -> bridge buyItem
SKILL_EXPLORE = "explore"  # plain forward walk — lets the agent traverse the world
SKILL_CAST_FROSTBOLT = "cast_frostbolt"  # mage: ranged dmg + 40% slow (kite enabler)
SKILL_CAST_FIREBALL = "cast_fireball"    # mage: ranged dmg + DoT (main nuke)
SKILL_CRAFT = "craft_item"               # craft a recipe whose reagents we have (ctx.recipeId)

# Outcome rewards (the agent learns these signs; no hard-coded rules)
# (мёртвый словарь REWARD удалён 2026-08-24: reward.py имеет свой WEIGHTS,
#  этот никогда не использовался — найдено аудитом обучающего контура)

# Phase gate: when the GoalFSM has an explicit goal, the Policy may only pick
# skills valid for that phase. This is what stops the agent from choosing a
# global action (e.g. explore) when it should be, say, returning the quest.
# DEAD/RESPAWN are handled outside decide() (in-process respawn glue).
# Use the SAME string literals as goal_fsm.py (NO_QUEST/FIND_GIVER/ACCEPT/
# DO_OBJECTIVE/RETURN_TO_GIVER/TURN_IN/SELL_REPAIR/HEAL) — they live in
# goal_fsm.py and are not imported here to avoid a circular dependency.
PHASE_ALLOWED = {
    "NO_QUEST":        [SKILL_ACCEPT, SKILL_EXPLORE],
    "FIND_GIVER":      [SKILL_ACCEPT, SKILL_EXPLORE],
    "ACCEPT":          [SKILL_ACCEPT],
    "DO_OBJECTIVE":    [SKILL_FARM, SKILL_LOOT, SKILL_GATHER,
                        SKILL_CAST_FROSTBOLT, SKILL_CAST_FIREBALL, SKILL_CRAFT],
    "RETURN_TO_GIVER": [SKILL_RETURN, SKILL_TURN_IN],
    "TURN_IN":         [SKILL_TURN_IN, SKILL_RETURN, SKILL_SELL],
    "SELL_REPAIR":     [SKILL_SELL, SKILL_BUY],
    "HEAL":            [SKILL_HEAL],
}
# craft_item is also valid in SELL_REPAIR (town visit: sell junk + craft at the
# forge/loom next door) — appended after the dict so DO_OBJECTIVE stays readable.
PHASE_ALLOWED["SELL_REPAIR"] = PHASE_ALLOWED["SELL_REPAIR"] + [SKILL_CRAFT]


def _softmax_sample(weights: Dict[str, float], temperature: float = 1.0,
                    counts: Optional[Dict] = None, bucket: Optional[str] = None,
                    exploration_weight: float = 1.0) -> str:
    """Sample an action proportional to exp(w/temp). Falls back to uniform on
    empty/zero weights (pure exploration).

    Exploration: rarely-tried (bucket, action) pairs get an optimistic bonus so the
    agent KEEPS trying them even after a bad lesson — farm must stay possible (P>0),
    never hard-forbidden by a zero weight. This is genuine exploration, not a
    scripted "farm allowed" rule.

    The count key MUST be the real (state_bucket, action) used by ExperienceStore.
    Previously the key was ("explore", action) — never present in the table — so the
    bonus was the same constant for every candidate and cancelled inside the softmax,
    making count-based exploration a silent no-op. `bucket` is now required for the
    bonus to do anything; without it the bonus is skipped entirely (honest uniform
    prior) rather than faked.

    `exploration_weight` (0..1) scales the bonus. Set to 0.0 for MEASUREMENT (frozen
    eval) so P(action) reflects Q only — this removes the exploration/visit-count
    confound when comparing BEFORE vs AFTER choice probabilities. Training keeps 1.0.
    """
    actions = list(weights.keys())
    if not actions:
        raise ValueError("no candidate actions")
    eff = {}
    for a in actions:
        w = weights[a]
        if counts is not None and bucket is not None and exploration_weight > 0.0:
            c = counts.get((bucket, a), 0) or 0
            # optimistic bonus, decays as the pair is actually tried
            w = w + exploration_weight * 0.5 / (1.0 + c * 0.1)
        eff[a] = w
    maxw = max(eff.values())
    exps = {a: math.exp((eff[a] - maxw) / max(temperature, 1e-3)) for a in actions}
    total = sum(exps.values())
    r = random.random() * total
    cum = 0.0
    for a in actions:
        cum += exps[a]
        if r <= cum:
            return a
    return actions[-1]


# Fix4 (2026-08-23): hints describe PAST behavior and must decay. A spin:hint
# journaled while an action was genuinely broken would otherwise suppress the
# repaired action forever — the loop could never re-admit it. 20 minutes is
# ~1 full SAVE_EVERY reflect() cycle x several: a still-true conclusion gets
# re-journaled with a fresh timestamp on every reflect(), so only genuinely
# stale conclusions expire.
HINT_TTL_SECONDS = 20 * 60

# Подавление залипшего скилла живёт в ВЕСАХ, не в членстве в кандидатах
# (см. комментарий в _candidates). x0.3 тормозит спам, но оставляет путь
# назад: починенный скилл снова победит, как только его Q подрастёт.
SPIN_WEIGHT_MULT = 0.3

# Q5 (консенсус 2026-08-24, вариант «гибрид»): gather предлагается ТОЛЬКО
# когда рядом есть объект действия (харвестный узел или труп с
# componentTags). Измерено: без гейта 25 из 171 шага (14.6%) уходили в
# пустой вызов. Чтобы не ослепнуть (мир меняется между снапшотами),
# раз в GATHER_PROBE_EVERY шагов делаем разведочную пробу вопреки фильтру —
# такая проба теперь честно верифицируется как failure при noTarget.
GATHER_PROBE_EVERY = 20


def load_reflection_hints(dirpath: Optional[str] = None) -> dict:
    """Load machine hints from self_reflection.json (the SelfReflection journal).

    Returns {key: {kind, detail, hint}} — e.g. {'spin:turn_in_quest': {...},
    'death:2_-3': {...}}. Empty dict when the file is absent/corrupt: hints are
    optional steering, never a hard dependency.
    """
    import json
    import time
    base = dirpath or os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "self_reflection.json")
    now = time.time()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        out = {}
        for c in data.get("journal", [])[-40:]:
            t = c.get("t")
            if not isinstance(t, (int, float)) or (now - t) > HINT_TTL_SECONDS:
                continue  # stale or timestamp-less -> no longer steering
            out[c.get("key")] = {"kind": c.get("kind"),
                                 "detail": c.get("detail"),
                                 "hint": c.get("hint")}
        return out
    except Exception:
        return {}


class GoalManager:
    def __init__(self, memory: ExperienceStore, temperature: float = 1.2, seed: int = None,
                 reflection_hints: Optional[dict] = None, strategy_memory=None):
        self.mem = memory
        # StrategyMemory (шаг 4 спеки 2026-08-24). Раньше она была
        # write-only: .preference() вызывался ТОЛЬКО в смоук-тесте, поэтому
        # доказанные стратегии не влияли ни на одно решение. Теперь политика
        # умножает вес доказанного навыка (мягкий prior, не override).
        self.strategy_memory = strategy_memory
        self.temperature = temperature
        # Self-learning loop (user 2026-08-22): hints from the agent's own
        # self-reflection journal steer candidate selection:
        #   spin:<action>  -> that action's weight is suppressed (x0.3)
        #   death:<cell>   -> farm suppressed in that cell while hp < 0.6
        self.hints = dict(reflection_hints or {})
        if seed is not None:
            random.seed(seed)

    # ---- build WorldState features from env info ----
    def _world_state(self, info: dict) -> dict:
        """Delegate to the SINGLE shared builder.

        This used to build its own partial dict (no distance_to_giver, no
        in_combat), which pinned the bucket's far/combat features to 0 while
        agent._world_state_dict() pinned mob/corpse/junk/danger to 0. The two
        buckets never matched, so lessons were unreadable by the decision path
        (measured by _diag_bucket.py). One builder = one bucket key.
        """
        return build_world_state(info)

    # ---- candidate skills from current world ----
    def _candidates(self, info: dict, ws: dict, goal: Optional[str] = None) -> List[str]:
        near = info.get("nearby") or []
        quest_npcs = [e for e in near
                      if (e.get("kind") == "npc" or e.get("type") == "npc")
                      and (e.get("questIds") or e.get("questId"))]
        corpses = [e for e in near
                   if (e.get("type") == "corpse" or e.get("kind") == "corpse" or e.get("lootable"))
                   and not e.get("looted")]
        mobs = [e for e in near if (e.get("kind") == "mob" or e.get("type") == "mob") and not e.get("lootable")]
        inv = info.get("inventory") or []
        junk = [i for i in inv if (i.get("quality") or 0) == 0]
        active = info.get("quests", {}).get("active") or []
        ready = info.get("quests", {}).get("ready") or []

        # Quest truth comes from the structured WorldState (ws["quest"]), NOT from
        # the raw info["quests"]["active"/"ready"] lists. The bridge sometimes omits
        # an active quest from those lists, so gating on them let the agent re-accept
        # an already-accepted quest (NPC: "already taken") -> FAILURE. The structured
        # view is computed from sim.questLog and is the authoritative source.
        qstruct = ws.get("quest") or {}
        quest_accepted = bool(qstruct.get("accepted"))
        quest_complete = bool(qstruct.get("complete"))
        cands = []
        if ws["hp_frac"] < 1.0:
            cands.append(SKILL_HEAL)           # always available, agent may or may not pick it
        # FARM only when a WEAK mob is near. Strong mobs (maxHp > player*1.3) would
        # kill the agent — offering farm on them just teaches a suicidal habit.
        # This is observation-driven (mob strength from world state), not a hard
        # "never farm" rule; the agent can still learn to farm when safe.
        if ws.get("weak_mob_near"):
            cands.append(SKILL_FARM)
        # Mage kit: ranged nukes. Offered only when a hostile mob is within
        # spell range (30yd, classes.ts) AND the spell is ready AND mana covers
        # the cost (world_state already folds both into abilities[].ready).
        # This is how the agent discovers it is a mage: the candidate exists,
        # the Q-table learns the rest (ranged kill before melee reach).
        if ws.get("has_ready_damage_spell"):
            cands.append(SKILL_CAST_FROSTBOLT)   # slow -> kiting possible
            cands.append(SKILL_CAST_FIREBALL)    # bigger hit + DoT
        # Economy: craft a recipe whose reagents are satisfied (and the required
        # station is in range for station-bound recipes). world_state already
        # computed ws["craftable_now"]; ctx carries the chosen recipeId.
        if ws.get("craftable_now"):
            cands.append(SKILL_CRAFT)
        if ws.get("has_mob") and info.get("targetId") is not None:
            # already in combat with something — allow finishing it even if strong
            cands.append(SKILL_FARM)
        if corpses:
            cands.append(SKILL_LOOT)
        # ИСПРАВЛЕНО 2026-08-24 (жалоба пользователя «квесты не берёт»):
        # раньше условием было `not quest_accepted`, где accepted — флаг ОДНОГО
        # выбранного квеста. При 10 активных квестах он всегда True, поэтому
        # accept_quest не предлагался НИКОГДА, даже когда рядом стояли NPC с
        # невзятыми квестами (замер: Weaver Ottilie и Tinker Gizzel, 4 новых
        # квеста, accept за 37 шагов — 0 раз).
        # Правильное условие: у NPC рядом есть квест, которого НЕТ в нашем логе.
        _quests = info.get("quests") or {}
        _have_ids = {q.get("id") for q in (_quests.get("active") or []) if q.get("id")}
        _have_ids |= {q.get("id") for q in (_quests.get("ready") or []) if q.get("id")}
        _have_ids |= {q.get("id") for q in (_quests.get("done") or []) if q.get("id")}
        # Гейт identity-transition из ИСХОДНИКОВ игры
        # (quest_commands.ts:104-109): пока в логе есть attune/amends/hobby
        # квест, остальные такие квесты имеют состояние unavailable. Без этой
        # проверки агент 7 раз стучался в закрытую дверь (все inconclusive).
        try:
            from quest_truth import accept_blocked_by_identity
        except Exception:
            accept_blocked_by_identity = lambda q, a: False
        _active_ids = [q.get("id") for q in (_quests.get("active") or []) if q.get("id")]
        has_new_quest_nearby = False
        for e in quest_npcs:
            ids = e.get("questIds") or ([e.get("questId")] if e.get("questId") else [])
            for qid in ids:
                if not qid or qid in _have_ids:
                    continue
                if accept_blocked_by_identity(qid, _active_ids):
                    continue          # игра не даст его взять
                has_new_quest_nearby = True
                break
            if has_new_quest_nearby:
                break
        if has_new_quest_nearby:
            cands.append(SKILL_ACCEPT)
        # Atomic quest-related actions. The Policy chooses among these — it is NOT
        # a single "do quest" button. turn_in only when ready (objectives done);
        # return_to_giver is always an option while a quest is active or ready
        # (agent may learn to use it when drifted far). complete_objective is NOT
        # auto-chosen here — the Policy picks plain FARM for progress (same
        # primitive), keeping the decision explicit.
        # Quest is ready ONLY when the structured view authoritatively says so
        # (complete=True: objectives present AND every current >= required). An
        # empty objective list must NOT count as "ready" — previously a freshly-
        # accepted quest with no progress was treated as turn-in-ready and the
        # agent ran straight to the giver without ever farming the objective mobs.
        # SURVIVAL GATE: at hp < 0.35 the agent must NOT walk anywhere (turn_in
        # / return both cross mob territory). Run 20132: hp=0.2 + turn_in spam
        # = death loop; heal+food regen needs SAFE ticks to actually fill HP.
        # Only when healthy again do the quest actions come back.
        quest_ready = (quest_complete or bool(ready)) and ws.get("hp_frac", 1.0) >= 0.35
        # Fix (2026-08-23): when the FSM phase is a turn-in/return phase, the
        # navigation + turn-in skills must ALWAYS be candidates — otherwise the
        # phase gate finds nothing to gate, falls back to the full list, and the
        # agent farms under a return phase (measured: goal=RETURN_TO_GIVER for 29
        # steps while actions were farm/loot/cast). The skills handle distance
        # honestly themselves (PARTIAL when far).
        if goal in ("RETURN_TO_GIVER", "TURN_IN") and ws.get("hp_frac", 1.0) >= 0.35:
            if SKILL_RETURN not in cands:
                cands.append(SKILL_RETURN)
            if SKILL_TURN_IN not in cands:
                cands.append(SKILL_TURN_IN)
        if quest_ready:
            cands.append(SKILL_TURN_IN)        # transactional: navigate + turn_in
            cands.append(SKILL_RETURN)         # navigation-only recovery leg
        # 2026-08-23: collect-квесты требуют предметы; если квестовый предмет уже
        # лежит в сумках (пусть не полный стек), harvest с ближайших трупов —
        # способ добить остаток (measured: spider_silk 5/6, loom ждал одну единицу).
        inv_map = {s.get("id"): s.get("count") for s in inv}
        quest_collect_pending = any(
            (qq.get("id") or "").startswith("q_prof_workorder")
            for qq in (active + ready))
        # объект действия для gather: харвестный узел ИЛИ труп с componentTags
        gather_nodes = [n for n in ((info.get("gather") or {}).get("nearbyNodes") or [])
                        if n.get("harvestable")]
        gather_corpses = [e for e in (info.get("nearby") or [])
                          if e.get("kind") == "mob" and e.get("dead")
                          and (e.get("componentTags") or [])]
        gather_object_near = bool(gather_nodes or gather_corpses)
        probe_now = (int(getattr(self, "step_idx", 0)) % GATHER_PROBE_EVERY == 0
                     and int(getattr(self, "step_idx", 0)) > 0)
        if quest_collect_pending and inv_map and (gather_object_near or probe_now):
            if SKILL_GATHER not in cands:
                cands.append(SKILL_GATHER)
        # Do not send an incomplete quest back to its giver prematurely.
        # Bag pressure: a nearly-full bag blocks quest turn-ins (bagsFullError)
        # even with zero junk-quality items (materials are common). Offer
        # sell_junk near a vendor when the bag is >=13 slots so the bridge's
        # material-surplus sale can free room. This is how "сумки полные ->
        # продай что-нибудь" becomes learnable instead of a silent wall.
        bag_slots = len([s for s in inv if s])
        bag_pressure = bag_slots >= 13 or bool(junk)
        if bag_pressure:
            # Only offer sell_junk when a vendor is actually nearby. Without
            # this the agent picks sell_junk while the vendor is far away, gets
            # an inconclusive (bridge no-ops "no merchant nearby"), and can
            # never reach the vendor because navigate_to_vendor does not exist.
            # Mirror the SKILL_BUY distance gate.
            ppos = info.get("player_pos") or [0, 0]
            # ИСПРАВЛЕНО 2026-08-24: радиус увеличен до 18 yd (было 12).
            # Агент застревал с полными сумками (26/16), потому что вендоры
            # были в 10-12 yd — чуть дальше порога. Сервер отклоняет сдачу
            # квеста (bagsFullError в quest_commands.ts:367-394), если награда
            # не влезает. Теперь агент видит вендора и может продать мусор.
            vendor_near = any(
                (e.get("kind") == "npc" or e.get("type") == "npc")
                and (e.get("vendor") or e.get("vendorItems") or e.get("isVendor"))
                and ((e.get("x", 0) - ppos[0]) ** 2 + (e.get("z", 0) - ppos[1]) ** 2) ** 0.5 <= 18
                for e in near
            )
            if vendor_near:
                cands.append(SKILL_SELL)
        # ИСПРАВЛЕНО 2026-08-24: форсированный sell_junk при критически полных сумках.
        # Сервер отклоняет сдачу квеста (bagsFullError), если награда не влезает.
        # Просто добавить sell_junk в кандидаты недостаточно — Q-table выбирает farm.
        # Теперь при >=16 слотов sell_junk добавляется с приоритетом (в начало списка).
        bag_critical = bag_slots >= 16
        if bag_critical and vendor_near:
            # Форсируем sell_junk — добавляем в начало, чтобы softmax выбрал его
            if SKILL_SELL not in cands:
                cands.insert(0, SKILL_SELL)
            else:
                # Перемещаем в начало списка — выше приоритет
                cands.remove(SKILL_SELL)
                cands.insert(0, SKILL_SELL)
        # gather: a harvestable node within reach (bridge harvestNode picks nearest
        # in radius 60). Only a candidate when such a node exists nearby.
        if any((e.get("kind") == "gather_node" or e.get("nodeType") or e.get("gatherTier") is not None)
               and not (e.get("dead") or e.get("depleted")) for e in near):
            cands.append(SKILL_GATHER)
        # equip: an unequipped gear item in the bag (bridge equipItem picks first
        # with def.equipSlot). Only a candidate when such an item exists.
        if any((i.get("def") or i.get("itemDef") or {}).get("equipSlot") for i in inv if i):
            cands.append(SKILL_EQUIP)
        # buy: a vendor NPC in range (bridge buyItem targets the nearest vendor).
        # Only a candidate when a vendor is actually nearby.
        ppos = info.get("player_pos") or [0, 0]
        if any((e.get("kind") == "npc" or e.get("type") == "npc")
               and (e.get("vendor") or e.get("vendorItems") or e.get("isVendor"))
               and ((e.get("x", 0) - ppos[0]) ** 2 + (e.get("z", 0) - ppos[1]) ** 2) ** 0.5 <= 12
               for e in near):
            cands.append(SKILL_BUY)
        # explore: plain forward walk. Genuine capability the policy may learn,
        # but NOT always-available: when a quest is active/ready the agent must
        # progress it (return_to_giver / turn_in), not drift to fences. Offer
        # explore only when there is NO active/ready quest AND no quest NPC is
        # nearby to interact with — i.e. early free-roam / discovery only.
        # Gate on the structured truth (quest_accepted), not the raw info lists.
        quest_active = quest_accepted or quest_complete
        quest_npc_near = bool(quest_npcs)
        if not quest_active and not quest_npc_near:
            cands.append(SKILL_EXPLORE)
        # phase gate: if the GoalFSM has an explicit goal, restrict candidates
        # to skills valid for that phase. This stops the policy from picking a
        # global action (e.g. explore) when it should be, say, returning the
        # quest. Healing is always allowed when hurt (survival > phase).
        if goal in PHASE_ALLOWED:
            allowed = PHASE_ALLOWED[goal]
            gated = [c for c in cands if c in allowed]
            if gated:
                cands = gated
            # else: no candidate matched the phase (e.g. giver not yet in range
            # for accept) -> fall back to the full list so the agent can act.
        if ws.get("hp_frac", 1.0) < 1.0 and SKILL_HEAL not in cands:
            cands.append(SKILL_HEAL)
        # SELF-LEARNING LOOP (closes the reflection cycle): the agent's own
        # conclusions change tomorrow's behavior.
        #   spin:<action> -> suppress that action (weight x0.3 at decide time,
        #     removed from candidates entirely when the journal is fresh)
        #   death:<cell>  -> while hp<0.6, no farm in a cell that killed us
        # 2026-08-24 (найдено со-архитектором): раньше здесь стоял
        # cands.remove(bad) — ЖЁСТКОЕ удаление скилла, хотя контракт обещает
        # подавление веса x0.3. Из-за этого spin:return_to_giver физически
        # вырезал скилл из кандидатов, детерминированный override фазы
        # RETURN_TO_GIVER не срабатывал, и агент не сдал ни одного квеста за
        # 1288 шагов. Теперь подавление живёт ТОЛЬКО в весах: скилл остаётся
        # кандидатом (self._suppressed), а decide() множит его вес на
        # SPIN_WEIGHT_MULT. Так залипание тормозится, но починенный скилл
        # всегда может вернуться.
        self._suppressed = set()
        for key, h in (self.hints or {}).items():
            if not isinstance(h, dict):
                continue
            kind = (h.get("kind") or "").upper()
            if "ACTION_SATURATION" in kind and key.startswith("spin:"):
                self._suppressed.add(key.split(":", 1)[1])
            # ШАГ 5 спеки (2026-08-24): раньше политика понимала ТОЛЬКО
            # spin: и death:, поэтому выводы рефлексии с ключами stall:/
            # cycle: загружались и молча игнорировались. Теперь понимаются
            # и событийные ключи от Event Bus.
            if key.startswith("stuck:") or key.startswith("stall:"):
                bad = key.split(":", 1)[1]
                if bad:
                    self._suppressed.add(bad)
            if ("DEATH" in kind and key.startswith("death:")
                    and ws.get("hp_frac", 1.0) < 0.6
                    and str(info.get("cell")) == key.split(":", 1)[1]):
                # ЗДЕСЬ жёсткое удаление ОПРАВДАНО и сохраняется: это не
                # анти-залипание, а гейт выживания — фармить в клетке, которая
                # нас уже убила, при hp<0.6 нельзя ни при каком весе.
                for risky in (SKILL_FARM,):
                    if risky in cands:
                        cands.remove(risky)
        # Retreat option: at low HP / in combat with an active quest, walking
        # back toward the giver is the only SURVIVABLE move (farm would re-engage
        # the mob that is killing us; heal may be a no-op without potions).
        # Without this the gated candidate set at crit HP is {farm, loot, heal}
        # and the agent is locked in a death loop (observed: 7 deaths in one run,
        # hp=0.2, still farming). Survival beats phase discipline — added AFTER
        # the phase gate so it survives DO_OBJECTIVE filtering.
        # GATE: only above the crit floor (hp>=0.35). Below it walking anywhere
        # is a death sentence (run 20132: hp=0.2 + turn_in spam); heal+food needs
        # safe ticks to fill HP back up.
        if (
            quest_accepted and ws.get("danger")
            and ws.get("hp_frac", 1.0) >= 0.35
            and SKILL_RETURN not in cands
        ):
            cands.append(SKILL_RETURN)
        # de-dup, preserve order
        seen = set(); out = []
        for c in cands:
            if c not in seen:
                seen.add(c); out.append(c)
        return out

    def _turn_ctx(self, info: dict, action: str) -> dict:
        """Ctx for return/turn-in skills: prefer the READY quest (it is the one
        that can actually be turned in), else the first active with turnInNpc."""
        quests = info.get("quests", {}) or {}
        ready = quests.get("ready") or []
        if ready:
            return {"quest": ready[0]}
        preferred = None
        for q in (quests.get("active") or []):
            if (q.get("turnInNpc") or {}).get("x") is not None:
                preferred = q
                break
        ctx = {}
        if preferred is not None:
            ctx["quest"] = preferred
        return ctx

    def _preferred_from_hints(self) -> set:
        """Навыки, которые рефлексия просит ПРЕДПОЧЕСТЬ (а не подавить).

        Раньше выводов такого рода не существовало вовсе: все хинты только
        душили действия. Полные сумки блокируют сдачу квеста (bagsFullError
        в turnInQuest), поэтому продажу нужно поощрять, а не подавлять.
        """
        out = set()
        for key, h in (self.hints or {}).items():
            if not isinstance(h, dict):
                continue
            hint = (h.get("hint") or "").lower()
            if hint == "prefer_sell" or key == "bags:full":
                out.add(SKILL_SELL)
            elif hint == "prefer_accept" or key == "quest:completed":
                out.add(SKILL_ACCEPT)
        return out

    def _strategy_key(self, info: dict, ws: dict):
        """Ключ стратегии = активный/готовый квест, к которому идёт работа."""
        q = (ws or {}).get("quest") or {}
        qid = q.get("id")
        if qid:
            return "quest:" + str(qid)
        quests = (info or {}).get("quests") or {}
        for bucket in ("ready", "active"):
            for item in (quests.get(bucket) or []):
                if item.get("id"):
                    return "quest:" + str(item["id"])
        return None

    def _strategy_weighted(self, vals: dict, info: dict, ws: dict) -> dict:
        """Умножить веса на множитель доказанной стратегии.

        Приёмка A2 спеки: навык, которым квест РЕАЛЬНО завершался, получает
        буст >=1.5x. Без StrategyMemory или без доказательств веса не меняются
        (обратная совместимость).
        """
        sm = getattr(self, "strategy_memory", None)
        if sm is None or not vals:
            return vals
        key = self._strategy_key(info, ws)
        if not key:
            return vals
        out = dict(vals)
        for action in list(out.keys()):
            try:
                mult = sm.boost(key, action)
            except Exception:
                mult = 1.0
            if mult != 1.0:
                v = out[action]
                # положительные веса усиливаем, отрицательные ослабляем —
                # буст не должен превращать плохой опыт в хороший
                out[action] = v * mult if v > 0 else v / mult
        return out

    # ---- main decision ----
    def decide(self, info: dict, ws: dict = None, exploration_weight: float = 1.0,
                goal: Optional[str] = None) -> Tuple[str, dict]:
        """Choose one skill. `ws` may be passed in by the caller so the decision
        and the later learn() call are guaranteed to use the SAME WorldState
        instance (and therefore the same bucket key). `exploration_weight` scales
        the count-based bonus; pass 0.0 at MEASUREMENT time so P reflects Q only
        (removes the exploration/visit-count confound)."""
        if ws is None:
            ws = self._world_state(info)
        cands = self._candidates(info, ws, goal=goal)
        # ПРИОРИТЕТ ВЫЖИВАНИЯ: полные сумки блокируют ВСЁ.
        # Сервер отклоняет сдачу квеста (bagsFullError в quest_commands.ts:367-394),
        # крафт и лут. Если сумки полные и есть вендор — форсируем sell_junk.
        import re as _re
        _mat_re = _re.compile(r'hide|fang|silk|gland|leg|scrap|cloth|weave|ore|bar|log|plank')
        inv_sell = info.get("inventory") or []
        bag_slots_sell = len([s for s in inv_sell if s])
        bag_capacity = ws.get("bag_capacity", 16)
        # Форсируем продажу когда сумки полные (остаётся < 3 слотов)
        if bag_slots_sell >= bag_capacity - 3 and SKILL_SELL in cands:
            keep_sell = set(ws.get("quest_items_needed", set()))
            keep_sell |= set(ws.get("craft_items_needed", set()))
            keep_sell |= {"baked_bread", "spring_water", "conjured_bread", "conjured_water", "copper_mining_pick"}
            counts_sell = {}
            for s in inv_sell:
                if not s: continue
                iid = s.get("itemId") or (s.get("def") or {}).get("id")
                if not iid: continue
                counts_sell[iid] = counts_sell.get(iid, 0) + (s.get("count") or 1)
            for iid, cnt in counts_sell.items():
                if iid in keep_sell: continue
                if not _mat_re.search(iid): continue
                if cnt - 3 >= 3:
                    return SKILL_SELL, {}
        # Ruling (2026-08-23): inside RETURN_TO_GIVER / TURN_IN phases the correct
        # skill is deterministic — navigate toward the giver, then turn in. Leaving
        # the choice to softmax let Q-values re-derive a farm/heal loop while the
        # ready quest waited (measured: 119 steps of RETURN_TO_GIVER with zero
        # return attempts). Survival gates still veto above.
        if goal == "RETURN_TO_GIVER" and ws.get("hp_frac", 1.0) >= 0.35 \
                and SKILL_RETURN in cands:
            return SKILL_RETURN, self._turn_ctx(info, SKILL_RETURN)
        if goal == "TURN_IN" and ws.get("hp_frac", 1.0) >= 0.35:

            # КОРНЕВОЙ ФИКС 2026-08-24 (подтверждён верификатором по исходникам):
            # сдача проходит ТОЛЬКО в пределах INTERACT_RANGE+2 = 7 ярдов
            # (quests/quest_commands.ts:148). Замер: гиверы были в 59-65 yd,
            # агент 67 шагов стоял в фазе TURN_IN, 7 раз вызвал turn_in_quest
            # (все INCONCLUSIVE) и НИ РАЗУ не пошёл к гиверу. Никакая правка
            # констант это не лечит — нужно ИДТИ.
            try:
                from quest_truth import QUEST_INTERACT_RANGE
            except Exception:
                QUEST_INTERACT_RANGE = 7.0
            _d = (ws.get("quest") or {}).get("giver_distance")
            if _d is None:
                _d = ws.get("distance_to_giver")
            if _d is not None and _d > QUEST_INTERACT_RANGE and SKILL_RETURN in cands:
                return SKILL_RETURN, self._turn_ctx(info, SKILL_RETURN)
            if SKILL_TURN_IN in cands:
                return SKILL_TURN_IN, self._turn_ctx(info, SKILL_TURN_IN)
        if not cands:
            return SKILL_FARM, {}
        vals = self.mem.candidate_values(ws, cands)
        # Доказанная стратегия (StrategyMemory) как мягкий prior над Q.
        vals = self._strategy_weighted(vals, info, ws)
        # Предпочтения из выводов рефлексии (полные сумки -> продать,
        # квест сдан -> взять следующий). Мягкий prior, не override.
        for _pref in self._preferred_from_hints():
            if _pref in vals:
                vals[_pref] = vals[_pref] * 1.6 if vals[_pref] > 0 else vals[_pref] + 0.4
        # Подавление залипших скиллов (spin:/death: хинты) — ЗДЕСЬ, в весах.
        # Скилл остаётся кандидатом, но его вес множится на SPIN_WEIGHT_MULT.
        for bad in getattr(self, "_suppressed", ()) or ():
            if bad in vals:
                v = vals[bad]
                vals[bad] = v * SPIN_WEIGHT_MULT if v > 0 else v - 0.2
        # ensure every candidate has an entry (unseen -> 0)
        bucket = _bucket(ws)   # SAME key ExperienceStore uses, so the count-based
                               # exploration bonus actually differentiates candidates
        action = _softmax_sample(vals, self.temperature, counts=self.mem.counts,
                                 bucket=bucket, exploration_weight=exploration_weight)
        # ctx: pass the active quest if relevant
        ctx = {}
        if action == SKILL_CRAFT:
            craftable = ws.get("craftable_now") or []
            if craftable:
                ctx["recipeId"] = craftable[0]["id"]
        if action == SKILL_SELL:
            # Умная продажа: не продавать нужное для квестов и крафта
            keep = set(ws.get("quest_items_needed", set()))
            keep |= set(ws.get("craft_items_needed", set()))
            ctx["keepIds"] = list(keep)
        if action == SKILL_FARM:
            # Таргетинг (2026-08-25): первая неполная kill-цель активного квеста.
            # Bridge фильтрует мобов по templateId — агент бьёт квестовых, а не
            # ближайших чужих. Нет kill-цели -> ctx пуст -> fallback на nearest.
            for qq in ((info.get("quests") or {}).get("active") or []):
                _done_q = True
                _mob = None
                for o in (qq.get("objectives") or []):
                    if o.get("type") == "kill" and o.get("targetMobId"):
                        cur = o.get("current") or 0
                        req = o.get("required") or 0
                        if cur < req:
                            _mob = o["targetMobId"]
                            _done_q = False
                            break
                if _mob:
                    ctx["targetMobId"] = _mob
                    break
        if action in (SKILL_TURN_IN, SKILL_RETURN, SKILL_ACCEPT):
            quests = info.get("quests", {}) or {}
            active = quests.get("active") or []
            ready = quests.get("ready") or []
            # turn_in needs a READY (objectives done) quest, not just any active
            if action == SKILL_TURN_IN and ready:
                ctx["quest"] = ready[0]
            else:
                # Prefer a quest that HAS a turnInNpc — return_to_giver navigates
                # to it. A quest without turnInNpc cannot be returned to, so skip
                # it when another quest with turnInNpc is available (mirrors
                # QuestCapability.find_active_quest). This fixes return_to_giver
                # FAILURE when quests.active[0] lacks turnInNpc.
                preferred = None
                for q in active:
                    if q.get("state") not in ("active", "ready", "complete"):
                        continue
                    if (q.get("turnInNpc") or {}).get("x") is not None:
                        ctx["quest"] = q
                        break
                    if preferred is None:
                        preferred = q
                else:
                    if preferred is not None:
                        ctx["quest"] = preferred
                if "quest" not in ctx and ready:
                    ctx["quest"] = ready[0]
            if action == SKILL_ACCEPT:
                for e in (info.get("nearby") or []):
                    if (e.get("kind") == "npc" or e.get("type") == "npc") and (e.get("questIds") or e.get("questId")):
                        ctx["npc"] = e
                        # CRITICAL: the questId must come from THIS npc's own
                        # questIds, NOT the first active quest (which may belong to
                        # a different NPC -> game rejects "quest unavailable").
                        qids = e.get("questIds") or e.get("questId") or []
                        if qids:
                            ctx["questId"] = qids[0] if isinstance(qids, (list, tuple)) else qids
                        ctx["npcId"] = e.get("id")
                        break
            elif action == SKILL_TURN_IN:
                # surface the ready quest's id so browser_env sends it
                rq = ctx.get("quest") or {}
                rid = rq.get("id") or rq.get("questId")
                if rid:
                    ctx["questId"] = rid
                # giver npc id from the ready quest's turnInNpc
                tNpcPlace = rq.get("turnInNpc") or {}
                if tNpcPlace.get("id") is not None:
                    ctx["npcId"] = str(tNpcPlace["id"])
            elif action in (SKILL_RETURN,):
                for q in active:
                    tNpc = q.get("turnInNpc") or {}
                    if tNpc.get("id") is not None:
                        ctx["npcId"] = str(tNpc["id"])
                        break
        return action, ctx

    def learn(self, ws: dict, action: str, reward: float, next_state: dict = None, outcome_kind: str = "OK", candidates: Optional[List[str]] = None):
        """Feed an outcome back into memory. ws is the SAME world-state the
        decision was made from (caller passes it). next_state is the resulting
        world-state, recorded as experience (real memory of what happened).
        `candidates` is the next state's reachable action set, passed to the TD
        bootstrap so it maxes only over reachable actions.
        """
        self.mem.update(ws, action, reward, next_state=next_state, outcome_kind=outcome_kind, candidates=candidates)
