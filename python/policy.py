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
import re
from typing import Any, Dict, List, Optional, Tuple

from memory import ExperienceStore, _bucket
from world_state import build_world_state
from class_config import get_class_config, get_playstyle, get_ability_for_class

# Skill names (must align with hierarchical_env.SKILLS indices)
SKILL_FARM = "farm"
SKILL_LOOT = "loot"
SKILL_ACCEPT = "accept_quest"
SKILL_TURN_IN = "turn_in_quest"
SKILL_RETURN = "return_to_giver"
SKILL_HEAL = "heal"
SKILL_NAVIGATE = "navigate"
SKILL_EXPLORE = "explore"
SKILL_SELL = "sell_junk"
SKILL_GATHER = "gather"
SKILL_EQUIP = "equip"      # equip tool from bag -> bridge equipItem
SKILL_BUY = "buy"          # vendor NPC in range -> bridge buyItem
SKILL_EXPLORE = "explore"  # plain forward walk — lets the agent traverse the world
SKILL_FLEE = "flee"        # run away from current target (survival)
SKILL_CAST_FROSTBOLT = "cast_frostbolt"  # mage: ranged dmg + 40% slow (kite enabler)
SKILL_CAST_FIREBALL = "cast_fireball"    # mage: ranged dmg + DoT (main nuke)
SKILL_CRAFT = "craft_item"               # craft a recipe whose reagents we have (ctx.recipeId)

# Чем в этой игре реально лечатся: зелья и еда. game_meat/rough_hide — сырьё
# профессий (src/sim/content/profession_items.ts), heal на них — no-op.
_HAS_HEAL_PAT = re.compile(r"potion|draught|tonic|elixir|heal|bread|water|jerky"
                           r"|roasted|cooked|meal|ration|cheese|apple", re.I)


def _has_healing(info: dict, ws: dict) -> bool:
    """Есть ли в сумках то, чем heal сработает. Нет данных -> считаем что нет."""
    items = None
    for src in (info, ws):
        if not isinstance(src, dict):
            continue
        for key in ("inventory_by_id", "inv_by_id"):
            cand = src.get(key)
            if isinstance(cand, dict) and cand:
                items = cand
                break
        if items is not None:
            break
    if not isinstance(items, dict) or not items:
        return False
    return any(_HAS_HEAL_PAT.search(str(k)) for k, v in items.items() if (v or 0) > 0)

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
    "NO_QUEST":        [SKILL_ACCEPT, SKILL_FARM, SKILL_EXPLORE],
    "FIND_GIVER":      [SKILL_ACCEPT, SKILL_EXPLORE],
    "ACCEPT":          [SKILL_ACCEPT],
    "DO_OBJECTIVE":    [SKILL_LOOT, SKILL_GATHER, SKILL_FARM,
                        SKILL_CAST_FROSTBOLT, SKILL_CAST_FIREBALL, SKILL_CRAFT,
                        SKILL_SELL, SKILL_FLEE, SKILL_RETURN, SKILL_NAVIGATE, SKILL_EXPLORE],
    "RETURN_TO_GIVER": [SKILL_RETURN, SKILL_TURN_IN, SKILL_FLEE],
    "TURN_IN":         [SKILL_TURN_IN, SKILL_RETURN, SKILL_SELL, SKILL_FLEE],
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
        # P1 №11 fix (2026-08-25): world_mem передаётся Agent'ом; раньше код
        # в decide() ссылался на несуществующее имя -> latent NameError.
        self.world_mem = None
        self._buy_state = {"fails": 0, "cooldown_until_step": -1, "last_item": None}
        self.step_idx = 0
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
        return build_world_state(info, getattr(self, "world_mem", None))

    # ---- candidate skills from current world ----
    def _candidates(self, info: dict, ws: dict, phase: str = None,
                    class_cfg: dict = None, playstyle: str = None,
                    advisor: dict = None) -> List[str]:
        # Класс игрока НЕ передавался параметром, хотя ниже используется для
        # выбора классовых способностей -> NameError на первом же шаге воина
        # (`gap_closer = get_ability_for_class(player_class, ...)`).
        # Берём его из тех же источников, что и decide().
        player_class = (info.get("player_class")
                        or (ws or {}).get("player_class")
                        or "warrior")
        # class_cfg/playstyle приходят не из всех вызовов (agent.py:392 зовёт
        # только с goal), а ниже идёт class_cfg["resource"] -> TypeError.
        # Выводим их из класса, если не передали.
        if class_cfg is None:
            class_cfg = get_class_config(player_class)
        if playstyle is None:
            playstyle = get_playstyle(player_class)
        near = info.get("nearby") or []
        quest_npcs = [e for e in near
                      if (e.get("kind") == "npc" or e.get("type") == "npc")
                      and (e.get("questIds") or e.get("questId"))]
        # ЛУТ — это труп МОБА в радиусе взаимодействия, а не любой объект с
        # lootable. В этой игре lootable стоит и у декораций/сундуков мира
        # (Ogre War Totem, Grave of..., Warded Shore-Rock — живой замер), они
        # лежат в 25-66 ярдах и никогда не лутаются: политика 153 шага подряд
        # звала loot -> inconclusive. Требуем kind=mob + dead + дистанцию.
        corpses = [e for e in near
                   if (e.get("type") == "corpse" or e.get("kind") == "corpse"
                       or ((e.get("kind") == "mob" or e.get("type") == "mob")
                           and (e.get("dead") or e.get("lootable"))))
                   and not e.get("looted")
                   and (e.get("dist") is None or (e.get("dist") or 0) <= 12.0)]
        mobs = [e for e in near if (e.get("kind") == "mob" or e.get("type") == "mob") and not e.get("lootable")]
        inv = info.get("inventory") or []
        # quality отсутствует в живом инвентаре (замер 2026-08-25) —
        # junk-детект по quality==0 помечал ВСЁ как хлам. Не используем.
        junk = []
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
        if ws["hp_frac"] < 1.0 and _has_healing(info, ws):
            # РАНЬШЕ heal предлагался всегда ("always available"), и при пустых
            # сумках это давало гарантированный failure на каждом шаге
            # (живой замер: 34 heal -> failure из 69 шагов). Реген работает сам.
            cands.append(SKILL_HEAL)
        # FARM — если есть моб (и слабый, и сильный). Раньше только weak_mob,
        # но тогда при strong_mob + objective almost complete агент застревал
        # в цикле explore → death. Рискнуть и фармить сильного моба лучше,
        # чем гарантированно умереть в пустую.
        if ws.get("has_mob"):
            # Если нет активного квеста и рядом есть гивер — убираем farm,
            # иначе агент будет бесконечно фермитить (farm имеет высокий Q).
            _no_quest = not ws.get("quest", {}).get("active")
            _world = ws.get("world") or {}
            _has_giver = len(_world.get("quest_givers") or []) > 0
            _near = info.get("nearby") or []
            _mob_in_melee = any(
                ((e.get("kind") == "mob" or e.get("type") == "mob")
                 and not e.get("lootable")
                 and (e.get("dist") is None or (e.get("dist") or 0) <= 5.0))
                for e in _near
            )
            if _no_quest and _has_giver and not _mob_in_melee:
                pass  # skip farm, prioritize quest taking
            else:
                cands.append(SKILL_FARM)
            # Дальний бой: mage/hunter
            primary = get_ability_for_class(player_class, "primary")
            ranged = get_ability_for_class(player_class, "ranged")
            if ws.get("has_ready_damage_spell") and primary:
                cands.append("cast_" + primary)
            if ws.get("has_ready_damage_spell") and ranged and ranged != primary:
                cands.append("cast_" + ranged)
        elif class_cfg["resource"] == "ranged" and playstyle == "melee":
            # Ближний бой: warrior — кастов нет, только farm (melee)
            # Но добавляем charge если враг далеко
            gap_closer = get_ability_for_class(player_class, "gap_closer")
            if gap_closer and ws.get("far_mob"):
                cands.append("cast_" + gap_closer)
        # Economy: craft a recipe whose reagents are satisfied (and the required
        # station is in range for station-bound recipes). world_state already
        # computed ws["craftable_now"]; ctx carries the chosen recipeId.
        if ws.get("craftable_now"):
            cands.append(SKILL_CRAFT)
        if ws.get("has_mob") and info.get("targetId") is not None:
            # already in combat with something — allow finishing it even if
            # strong, НО не самоубийственно: цель с 1500 HP против воина
            # 1-го уровня с 29 HP не «дожимается», это гарантированная смерть
            # (живой замер: deaths=55, kills=1, зона Warlord Drogmar 1564 HP).
            # Безнадёжный бой -> farm не предлагаем, пусть работает отступление.
            _tgt_max = 0.0
            for _e in near:
                if _e.get("id") == info.get("targetId"):
                    _tgt_max = float(_e.get("maxHp") or 0)
                    break
            _pmax = float((info.get("player") or {}).get("maxHp") or 0) or 1.0
            if _tgt_max <= _pmax * 3.0:
                # Only offer farm if the target is within attack range
                # Use nearest_mob_distance from world state (reliable computed distance)
                _nearest = ws.get("nearest_mob_distance")
                if _nearest is not None and _nearest <= 10.0:
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
        # FIX #1 (2026-08-27): has_new_quest_nearby должен учитывать quest_states.
        # Раньше: если у NPC есть questId, которого нет в логе — accept_quest добавлялся
        # в кандидаты. Но quest_states[questId] мог быть "unavailable" → skill_contracts
        # блокировал (quest_available=False) → INCONCLUSIVE → зацикливание (70+ шагов).
        quest_states = info.get("quest_states") or {}
        has_new_quest_nearby = False
        for e in quest_npcs:
            ids = e.get("questIds") or ([e.get("questId")] if e.get("questId") else [])
            for qid in ids:
                if not qid or qid in _have_ids:
                    continue
                if accept_blocked_by_identity(qid, _active_ids):
                    continue          # игра не даст его взять
                if quest_states.get(qid) != "available":
                    continue          # квест недоступен (unavailable/active/done)
                has_new_quest_nearby = True
                break
            if has_new_quest_nearby:
                break
        if has_new_quest_nearby:
            # CRITICAL: If we already have an active quest, DO NOT offer accept_quest.
            # This prevents the accept_quest → accept_quest → accept_quest loop.
            _have_active = bool(info.get("quests", {}).get("active"))
            if not _have_active:
                cands.append(SKILL_ACCEPT)
            # If we have an active quest, ensure accept_quest is NOT in candidates
            elif SKILL_ACCEPT in cands:
                cands.remove(SKILL_ACCEPT)
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
        quest_ready = bool(quest_complete or ready)
        # Fix (2026-08-23): when the FSM phase is a turn-in/return phase, the
        # navigation + turn-in skills must ALWAYS be candidates — otherwise the
        # phase gate finds nothing to gate, falls back to the full list, and the
        # agent farms under a return phase (measured: goal=RETURN_TO_GIVER for 29
        # steps while actions were farm/loot/cast). The skills handle distance
        # honestly themselves (PARTIAL when far).
        goal_phase = phase  # passed directly from arbitration layer
        # Survival gate: at hp < 0.35 suppress walking skills that cross mob
        # territory (turn_in/return) — death loop (measured: run 20132 hp=0.2 +
        # turn_in spam). EXCEPTION: when in danger (combat), escape skills
        # (flee, return_to_giver) MUST remain available — otherwise the agent
        # is locked in place and dies. Heal/food can fill HP in SAFE ticks.
        in_danger = bool(ws.get("danger") or ws.get("in_combat"))
        safe_to_walk = ws["hp_frac"] >= 0.35 or in_danger
        if goal_phase in ("RETURN_TO_GIVER", "TURN_IN") and safe_to_walk:
            if SKILL_RETURN not in cands:
                cands.append(SKILL_RETURN)
            if SKILL_TURN_IN not in cands and ws["hp_frac"] >= 0.35:
                cands.append(SKILL_TURN_IN)
        if ws["hp_frac"] >= 0.35 and quest_ready:
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
        # 2026-08-25 (сбор ресурсов): gather-квесты (type:gather nodeType:X)
        # теперь ВСЕГДА дают gather-кандидата — мост умеет идти к статическим
        # узлам (EASTBROOK_GATHER_NODES), дальность больше не блокер.
        # nodeType квеста кладём в ctx для приоритета типа узла.
        self._gather_node_type = None
        for qq in ((info.get("quests") or {}).get("active") or []):
            for o in (qq.get("objectives") or []):
                if o.get("type") == "gather" and o.get("nodeType"):
                    cur = o.get("current") or 0
                    req = o.get("required") or 0
                    if cur < req:
                        self._gather_node_type = o["nodeType"]
                        if SKILL_GATHER not in cands:
                            cands.append(SKILL_GATHER)
                        break
            if self._gather_node_type:
                break
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
        # Only a candidate when a vendor is actually within INTERACT_RANGE (5 yards).
        # Official Sim uses INTERACT_RANGE = 5 for all interactions.
        ppos = info.get("player_pos") or [0, 0]
        VENDOR_INTERACT_RANGE = 5.0  # matches official Sim INTERACT_RANGE
        if any((e.get("kind") == "npc" or e.get("type") == "npc")
               and (e.get("vendor") or e.get("vendorItems") or e.get("isVendor"))
               and ((e.get("x", 0) - ppos[0]) ** 2 + (e.get("z", 0) - ppos[1]) ** 2) ** 0.5 <= VENDOR_INTERACT_RANGE
               for e in near):
            cands.append(SKILL_BUY)
        # If vendor is visible but not in interact range, offer navigate to approach
        elif any((e.get("kind") == "npc" or e.get("type") == "npc")
                 and (e.get("vendor") or e.get("vendorItems") or e.get("isVendor"))
                 for e in near):
            if "navigate" not in cands:
                cands.append("navigate")
        # explore: plain forward walk. Genuine capability the policy may learn,
        # but NOT always-available: when a quest is active/ready the agent must
        # progress it (return_to_giver / turn_in / farm), not drift to fences.
        # Offer explore only when there is NO active/ready quest AND no quest NPC
        # is nearby to interact with — i.e. early free-roam / discovery only.
        # Gate on the STRUCTURED quest_status (authoritative, from sim.questLog),
        # not on quest_accepted alone: the latter was observed to desync from the
        # FSM goal (fsm stayed NO_QUEST while quest_status==ACTIVE), which let
        # explore slip in and the agent wandered to dist=290yd away from the
        # giver. quest_status is the single source of truth for "is a quest on?".
        quest_status = ws.get("quest_status")
        quest_active = quest_status in ("ACTIVE", "READY_TO_TURN_IN", "DONE")
        quest_npc_near = bool(quest_npcs)
        if not quest_active and not quest_npc_near:
            cands.append(SKILL_EXPLORE)
        # phase gate: if the GoalFSM has an explicit goal, restrict candidates
        # to skills valid for that phase. This stops the policy from picking a
        # global action (e.g. explore) when it should be, say, returning the
        # quest. Healing is always allowed when hurt (survival > phase).
        # 2026-09-03 FIX: goal включает quest_id ("DO_OBJECTIVE:q_wolves"),
        # а PHASE_ALLOWED ключи без суффикса. Извлекаем фазу перед проверкой.
        goal_phase = phase  # passed directly from arbitration layer
        if goal_phase in PHASE_ALLOWED:
            allowed = PHASE_ALLOWED[goal_phase]
            gated = [c for c in cands if c in allowed]
            if gated:
                cands = gated
            # else: no candidate matched the phase (e.g. giver not yet in range
                # for accept) -> fall back to the full list so the agent can act.
        if (ws.get("hp_frac", 1.0) < 1.0 and SKILL_HEAL not in cands
                and _has_healing(info, ws)):
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
        # Retreat option removed — safety gate handles this in arbitration layer.
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
            elif key == "autonomy_subgoal":
                # Подсказка автономного контура: планировщик знает, какой шаг
                # ведёт к цели активного квеста. Это ПРЕДПОЧТЕНИЕ, не приказ —
                # выбор остаётся за политикой, но без этого канала контур
                # считал шаги, а поведение не менялось (живой замер: 69 шагов,
                # только heal/loot, ни одного farm/explore).
                sk = h.get("skill") or h.get("hint")
                if sk:
                    out.add(sk)
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

    def _log_decision(self, ws, info, goal_phase, reason, action, q_values, chooser, extra=None):
        """Telemetry: log WHO decided and WHY. Writes to decision_log.jsonl."""
        try:
            import json, os, time
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "decision_log.jsonl")
            bucket = _bucket(ws)
            entry = {
                "t": time.time(),
                "step": getattr(self, "step_idx", -1),
                "bucket": bucket,
                "goal_phase": goal_phase,
                "chooser": chooser,
                "reason": reason,
                "action": action,
                "q_values": {k: round(v, 4) for k, v in (q_values or {}).items()},
                "cands": list(q_values.keys()) if q_values else [],
                "hp_frac": ws.get("hp_frac"),
                "quest_status": ws.get("quest_status"),
                "giver_dist": ws.get("distance_to_giver"),
                "extra": extra or {},
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # telemetry must never crash the agent

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

    # ---- main decision (Phase 5: data-only, no early returns) ----
    def decide(self, info: dict, ws: dict = None, exploration_weight: float = 1.0,
                phase: Optional[str] = None,
                context: "DecisionContext" = None,
                advisor: Optional[dict] = None,
                allowed: Optional[List[str]] = None) -> Tuple[Dict[str, float], List[str], Dict[str, Any]]:
        """Compute Q-values for candidates. NO early returns.

        Phase 5 contract: returns data only. ArbitrationLayer decides.

        Returns:
            q_values: {action: weight} for all candidates
            candidates: list of valid action names
            metadata: {suppressed, preferred, forced_skill, ...} for arbitration
        """
        if ws is None:
            ws = self._world_state(info)
        goal_phase = phase
        player_class = (info.get("player_class")
                        or (ws or {}).get("player_class")
                        or "warrior")
        class_cfg = get_class_config(player_class)
        playstyle = get_playstyle(player_class)
        cands = self._candidates(info, ws, phase=phase,
                                  class_cfg=class_cfg, playstyle=playstyle)
        if allowed is not None:
            cands = [c for c in cands if c in allowed] or list(allowed)
        if goal_phase == "DO_OBJECTIVE" and ws.get("quest", {}).get("id"):
            if "navigate" not in cands:
                cands.append("navigate")
        # If no mob in attack range but there's a mob nearby, offer navigate
        # to approach it. Prevents farm/heal looping at long range.
        # PLAYER_INTEREST_RADIUS in official Sim is 90 yards.
        if not ws.get("has_mob") and "navigate" not in cands:
            _nearest = ws.get("nearest_mob_distance")
            if _nearest is not None and _nearest <= 100.0:
                cands.append("navigate")
        if context is not None:
            _masked = list(context.allowed_skills)
            filtered = [c for c in cands if c in _masked]
            if filtered:
                cands = filtered
            elif _masked:
                if goal_phase == "DO_OBJECTIVE" and "navigate" in _masked:
                    cands = ["navigate"]
                else:
                    cands = [_masked[0]]
        elif hasattr(self, "hints") and self.hints.get("masked_candidates"):
            _masked = self.hints.get("masked_candidates")
            filtered = [c for c in cands if c in _masked]
            if filtered:
                cands = filtered
            elif "explore" in _masked:
                cands = ["explore"]

        # Build metadata for arbitration layer
        metadata = {
            "goal_phase": goal_phase,
            "suppressed": set(),
            "preferred": set(),
            "forced_skill": None,
            "deterministic_action": None,
        }

        # Check for deterministic actions (passed to arbitration, not returned directly)
        # Plan-stack: READY quest at giver (dist<=6) -> turn_in immediately
        if (ws.get("quest_status") == "READY_TO_TURN_IN"
                and ws.get("quest", {}).get("giver_distance", 999) <= 6):
            qid = ws.get("quest", {}).get("id")
            ctx = {}
            if qid:
                ctx["questId"] = qid
                ctx["quest"] = {"id": qid}
            metadata["deterministic_action"] = (SKILL_TURN_IN, ctx, "plan_stack_turn_in")

        # Tool priority: gather quest needs tool -> buy (with cooldown)
        if metadata["deterministic_action"] is None:
            _tool_need = ws.get("needs_tool")
            if _tool_need:
                has_tool = any(
                    s.get("itemId") == _tool_need
                    for s in (info.get("inventory") or [])
                )
                _buy_state = getattr(self, "_buy_state", None)
                _step_idx = getattr(self, "step_idx", 0) or 0
                if not has_tool and _buy_state is not None:
                    if _step_idx >= _buy_state.get("cooldown_until_step", -1):
                        ctx = {"buyItemId": _tool_need}
                        _world_mem = getattr(self, "world_mem", None)
                        if _world_mem is not None:
                            vendor = _world_mem.vendor_pos("trader_wilkes")
                            if vendor:
                                ctx["vendorPos"] = vendor
                        metadata["deterministic_action"] = ("buy", ctx, "tool_priority")

        # Bag survival: bags almost full -> sell_junk (if vendor near)
        if metadata["deterministic_action"] is None:
            from arbitration import _vendor_nearby, _corpses_nearby, _giver_distance, _turn_ctx
            inv = info.get("inventory") or []
            bag_slots = len([s for s in inv if s])
            bag_capacity = ws.get("bag_capacity", 16)
            if bag_slots >= bag_capacity - 3:
                if _vendor_nearby(info):
                    keep = set(ws.get("quest_items_needed", set()))
                    keep |= set(ws.get("craft_items_needed", set()))
                    keep |= {"baked_bread", "spring_water", "conjured_bread", "conjured_water", "copper_mining_pick"}
                    counts = {}
                    for s in inv:
                        if not s:
                            continue
                        iid = s.get("itemId") or (s.get("def") or {}).get("id")
                        if not iid:
                            continue
                        counts[iid] = counts.get(iid, 0) + (s.get("count") or 1)
                    for iid, cnt in counts.items():
                        if iid in keep:
                            continue
                        if cnt - 3 >= 3:
                            metadata["deterministic_action"] = (SKILL_SELL, {"keepIds": list(keep)}, "bag_survival")
                            break

        # Loot priority: corpses nearby -> loot
        if metadata["deterministic_action"] is None:
            from arbitration import _corpses_nearby
            corpses = _corpses_nearby(info)
            if corpses and SKILL_LOOT in cands:
                metadata["deterministic_action"] = (SKILL_LOOT, {}, "loot_priority")

        # Phase return: RETURN_TO_GIVER -> return_to_giver
        if metadata["deterministic_action"] is None and goal_phase == "RETURN_TO_GIVER":
            from arbitration import _turn_ctx
            if ws.get("hp_frac", 1.0) >= 0.35 and SKILL_RETURN in cands:
                metadata["deterministic_action"] = (SKILL_RETURN, _turn_ctx(info, SKILL_RETURN), "phase_return")

        # Turn-in phase: TURN_IN -> turn_in or return
        if metadata["deterministic_action"] is None and goal_phase == "TURN_IN":
            from arbitration import _giver_distance, _turn_ctx
            d = _giver_distance(ws)
            if d is not None:
                if d > QUEST_INTERACT_RANGE and SKILL_RETURN in cands:
                    metadata["deterministic_action"] = (SKILL_RETURN, _turn_ctx(info, SKILL_RETURN), "turn_in_phase_return")
                elif SKILL_TURN_IN in cands:
                    metadata["deterministic_action"] = (SKILL_TURN_IN, _turn_ctx(info, SKILL_TURN_IN), "turn_in_phase_turn_in")

        # Compute Q-values (always, even if deterministic_action is set)
        if not cands:
            # No candidates — return empty, arbitration handles fallback
            return {}, [], metadata

        vals = self.mem.candidate_values(ws, cands)
        vals = self._strategy_weighted(vals, info, ws)
        for _pref in self._preferred_from_hints():
            if _pref in vals:
                vals[_pref] = vals[_pref] * 1.6 if vals[_pref] > 0 else vals[_pref] + 0.4
        for bad in getattr(self, "_suppressed", ()) or ():
            if bad in vals:
                v = vals[bad]
                vals[bad] = v * SPIN_WEIGHT_MULT if v > 0 else v - 0.2
                metadata["suppressed"].add(bad)
        _cur_target = ws.get("target_mob_id") if isinstance(ws, dict) else None
        if _cur_target and SKILL_FARM in vals:
            _neg = self.mem.negative_targets("farm")
            if _cur_target in _neg:
                v = vals[SKILL_FARM]
                vals[SKILL_FARM] = v * SPIN_WEIGHT_MULT if v > 0 else v - 0.2
                metadata["suppressed"].add(SKILL_FARM)
        if advisor:
            _adv_subgoal = advisor.get("subgoal")
            _adv_target = advisor.get("target_mob_id")
            if _adv_subgoal == "KILL" and SKILL_FARM in vals:
                v = vals[SKILL_FARM]
                vals[SKILL_FARM] = v * 1.2 if v > 0 else v + 0.2
            elif _adv_subgoal == "GATHER" and SKILL_GATHER in vals:
                v = vals[SKILL_GATHER]
                vals[SKILL_GATHER] = v * 1.2 if v > 0 else v + 0.2
            elif _adv_subgoal == "FIND_MOB" and SKILL_EXPLORE in vals:
                v = vals[SKILL_EXPLORE]
                vals[SKILL_EXPLORE] = v * 1.15 if v > 0 else v + 0.15
            elif _adv_subgoal == "TURN_IN" and SKILL_TURN_IN in vals:
                v = vals[SKILL_TURN_IN]
                vals[SKILL_TURN_IN] = v * 1.3 if v > 0 else v + 0.3
            elif _adv_subgoal == "RETURN_TO_GIVER" and SKILL_RETURN in vals:
                v = vals[SKILL_RETURN]
                vals[SKILL_RETURN] = v * 1.3 if v > 0 else v + 0.3

        # Store for telemetry
        self._trace_vals = dict(vals)
        self._trace_cands = list(cands)

        return vals, list(cands), metadata

    def _decide_legacy(self, info: dict, ws: dict = None, exploration_weight: float = 1.0,
                phase: Optional[str] = None,
                context: "DecisionContext" = None,
                advisor: Optional[dict] = None,
                allowed: Optional[List[str]] = None) -> Tuple[str, dict]:
        """Legacy decide() — returns (action, ctx). Kept for backward compatibility with tests."""
        vals, cands, metadata = self.decide(info, ws, exploration_weight, phase, context, advisor, allowed)

        # If deterministic action is set, return it directly
        if metadata.get("deterministic_action"):
            return metadata["deterministic_action"][:2]

        if not cands:
            return SKILL_FARM, {}

        # Sample from Q-values
        bucket = _bucket(ws) if ws is not None else None
        action = _softmax_sample(vals, self.temperature, counts=self.mem.counts,
                                 bucket=bucket, exploration_weight=exploration_weight)

        # Build ctx
        ctx = self._build_action_ctx(action, info, ws)
        return action, ctx

    def _build_action_ctx(self, action: str, info: dict, ws: dict) -> dict:
        """Build context dict for the chosen action."""
        ctx = {}
        if action == SKILL_CRAFT:
            craftable = ws.get("craftable_now") or []
            if craftable:
                ctx["recipeId"] = craftable[0]["id"]
        if action == SKILL_GATHER and getattr(self, "_gather_node_type", None):
            ctx["nodeType"] = self._gather_node_type
        if action == SKILL_SELL:
            keep = set(ws.get("quest_items_needed", set()))
            keep |= set(ws.get("craft_items_needed", set()))
            ctx["keepIds"] = list(keep)
        if action == SKILL_BUY:
            need = ws.get("needs_tool")
            if need:
                ctx["buyItemId"] = need
                vendor = self.world_mem.vendor_pos("trader_wilkes") if getattr(self, "world_mem", None) else None
                if vendor:
                    ctx["vendorPos"] = vendor
        if action == SKILL_FARM:
            for qq in ((info.get("quests") or {}).get("active") or []):
                _mob = None
                for o in (qq.get("objectives") or []):
                    if o.get("type") == "kill" and o.get("targetMobId"):
                        cur = o.get("current") or 0
                        req = o.get("required") or 0
                        if cur < req:
                            _mob = o["targetMobId"]
                            break
                if _mob:
                    ctx["targetMobId"] = _mob
                    break
        if action in (SKILL_TURN_IN, SKILL_RETURN, SKILL_ACCEPT):
            quests = info.get("quests", {}) or {}
            active = quests.get("active") or []
            ready = quests.get("ready") or []
            if action == SKILL_TURN_IN and ready:
                ctx["quest"] = ready[0]
            else:
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
                        ctx["npcId"] = e.get("id")
                        qids = e.get("questIds") or e.get("questId") or []
                        qids_list = qids if isinstance(qids, (list, tuple)) else [qids]
                        avail = (quests.get("available") or [])
                        chosen = None
                        for qid in qids_list:
                            if any((aq.get("id") == qid or aq.get("questId") == qid) for aq in avail):
                                chosen = qid
                                for aq in avail:
                                    if (aq.get("id") == qid or aq.get("questId") == qid):
                                        ctx["quest"] = aq
                                        break
                                break
                        if chosen is None and qids_list:
                            chosen = qids_list[0]
                        if chosen:
                            ctx["questId"] = chosen
                        break
            elif action == SKILL_TURN_IN:
                rq = ctx.get("quest") or {}
                rid = rq.get("id") or rq.get("questId")
                if rid:
                    ctx["questId"] = rid
                tNpcPlace = rq.get("turnInNpc") or {}
                if tNpcPlace.get("id") is not None:
                    ctx["npcId"] = str(tNpcPlace["id"])
            elif action in (SKILL_RETURN,):
                for q in active:
                    tNpc = q.get("turnInNpc") or {}
                    if tNpc.get("id") is not None:
                        ctx["npcId"] = str(tNpc["id"])
                        ctx["quest"] = q
                        rid = q.get("id") or q.get("questId")
                        if rid:
                            ctx["questId"] = rid
                        break
        return ctx

    def learn(self, ws: dict, action: str, reward: float, next_state: dict = None, outcome_kind: str = "OK", candidates: Optional[List[str]] = None):
        """Feed an outcome back into memory. ws is the SAME world-state the
        decision was made from (caller passes it). next_state is the resulting
        world-state, recorded as experience (real memory of what happened).
        `candidates` is the next state's reachable action set, passed to the TD
        bootstrap so it maxes only over reachable actions.
        """
        self.mem.update(ws, action, reward, next_state=next_state, outcome_kind=outcome_kind, candidates=candidates)
        # J5: record identity-aware episodic memory when there's a target
        target_id = ws.get("target_mob_id") if isinstance(ws, dict) else None
        if target_id:
            self.mem.record_episodic(
                ws, action, reward, outcome_kind,
                goal=self._strategy_key(ws, ws) if isinstance(ws, dict) else None,
                cause=f"target={target_id}",
                lesson=f"{action} on {target_id} -> {outcome_kind} (r={reward:+.2f})",
            )
        # P0 №5 (stateful buy): считаем неудачи покупки -> cooldown 30 шагов
        # после 3 неудач ПО ОДНОМУ И ТОМУ ЖЕ предмету. Успех сбрасывает.
        # Fix (review 1d4cceb): last_item устанавливается при КАЖДОЙ попытке,
        # раньше оставался None и счётчик никогда не инкрементировался.
        if action == SKILL_BUY:
            item = ws.get("needs_tool")
            if reward > 0:
                self._buy_state["fails"] = 0
                self._buy_state["last_item"] = None
            elif item:
                if self._buy_state["last_item"] == item:
                    self._buy_state["fails"] += 1
                else:
                    self._buy_state["last_item"] = item
                    self._buy_state["fails"] = 1
                if self._buy_state["fails"] >= 3:
                    self._buy_state["cooldown_until_step"] = (self.step_idx or 0) + 30
