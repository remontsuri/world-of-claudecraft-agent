"""planner.py — Planner выше PPO (ARCHITECTURE.md §5).

PPO не должен с нуля выучивать смысл игры. Planner раскладывает objective
квеста в последовательность subgoal-ов, а политика выбирает КАК выполнить
текущий subgoal.

    QUEST: collect 8 ironbark
      -> GET_TOOL -> GO_TO_NODE -> GATHER xN -> RETURN_TO_GIVER -> TURN_IN

План — данные (список шагов). Planner не трогает игру и не решает,
какое действие послать в мост: он говорит, какой шаг сейчас актуален.

STREAM J3 (memory-aware planning):
- Planner читает StrategyMemory и ExperienceStore перед генерацией плана.
- При повторном планировании того же goal — генерирует альтернативу, а не
  повторяет провальный шаблон.
- Логирует: planned_step -> result -> lesson.
"""
import re
from typing import Any, Dict, List, Optional

# Соответствие nodeType/itemId -> инструмент. Имена сверены с ЖИВЫМ
# ассортиментом вендоров (probe 2026-08-25): logging_axe/herb_sack В ИГРЕ НЕТ.
TOOL_FOR_NODE: Dict[str, str] = {
    "wood": "handaxe",
    "timber": "handaxe",
    "herb": "gathering_sickle",
    "herbalism": "gathering_sickle",
    "ore": "copper_mining_pick",
    "mining": "copper_mining_pick",
}
TOOL_FOR_ITEM: Dict[str, str] = {
    "ironbark_log": "handaxe",
    "pine_log": "handaxe",
    "copper_ore": "copper_mining_pick",
    "tin_ore": "copper_mining_pick",
}


def required_tool(objective: Dict[str, Any]) -> Optional[str]:
    """Какой инструмент нужен для gather-цели (None если не нужен)."""
    if not objective:
        return None
    node = (objective.get("node_type") or objective.get("nodeType") or "")
    if node:
        t = TOOL_FOR_NODE.get(str(node).lower())
        if t:
            return t
    item = (objective.get("item_id") or objective.get("itemId") or "")
    if item:
        return TOOL_FOR_ITEM.get(str(item).lower())
    return None


def _has_tool(obs: Dict[str, Any], tool: str) -> bool:
    """Инструмент есть, если world_state не считает его отсутствующим."""
    if not tool:
        return True
    inv = obs.get("inventory") or {}
    missing = inv.get("missing_tool")
    if missing and str(missing) == str(tool):
        return False
    owned = inv.get("tools") or inv.get("item_ids") or []
    if owned:
        return tool in owned
    # нет данных о наличии -> считаем что есть (не блокируем цикл)
    return not missing


# Чем в этой игре можно вылечиться: зелья и еда. game_meat/rough_hide — это
# сырьё профессий (src/sim/content/profession_items.ts), а НЕ еда: спамить
# ими heal бессмысленно.
_HEAL_PAT = re.compile(r"potion|draught|tonic|elixir|heal|bread|water|jerky"
                       r"|roasted|cooked|meal|ration|cheese|apple", re.I)


def _can_heal(obs) -> bool:
    """Есть ли в сумках то, чем heal реально сработает."""
    inv = (obs or {}).get("inventory") or {}
    items = inv.get("items")
    if not isinstance(items, dict):
        return False                      # состав сумок неизвестен -> не врём
    return any(_HEAL_PAT.search(str(k)) for k, v in items.items() if (v or 0) > 0)


def plan_subgoals(obs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Разложить текущее состояние в последовательность subgoal-ов.

    Порядок отражает приоритеты автономного цикла:
      1. умер -> respawn
      2. критический HP -> отступить и лечиться
      3. сумки полны -> продать
      4. есть READY-квест -> вернуться и сдать
      5. есть активная цель -> (инструмент) -> выполнять цель
      6. рядом гивер с квестом -> взять квест
      7. иначе -> исследовать
    """
    obs = obs or {}
    player = obs.get("player") or {}
    quest = obs.get("quest") or {}
    inv = obs.get("inventory") or {}
    world = obs.get("world") or {}

    # 1. смерть
    if player.get("dead"):
        return [{"subgoal": "RESPAWN", "skill": "respawn", "reason": "player_dead"}]

    # 2. критический HP
    hp = player.get("hp_fraction")
    if hp is not None and hp < 0.35:
        # heal имеет смысл, только если есть ЧЕМ лечиться (зелье/еда). Иначе
        # это no-op, и агент застревает в SURVIVE, пока реген идёт сам собой
        # (живой замер: hp 29%, ни зелий, ни еды, 5 шагов heal подряд впустую).
        if _can_heal(obs):
            return [{"subgoal": "SURVIVE", "skill": "heal",
                     "reason": "hp_critical"}]
        # лечиться нечем: уходим от опасности, реген сделает своё.
        # Отдельного «сесть» в игре нет (sitting включается только едой,
        # src/sim/items.ts:791), поэтому вне боя просто ждём — noop лучше,
        # чем спам heal, который ничего не делает и засоряет replay.
        if (world.get("nearby_mobs") or 0) > 0:
            # RETREAT removed: let policy decide (farm/heal/explore).
            # _retreat_if_needed in autonomous_master.py handles physical
            # retreat when in combat. Policy learns survival via reward.
            pass
        return [{"subgoal": "REGEN", "skill": "noop",
                 "reason": "hp_critical_no_heal"}]

    # 3. сумки полны -> продать (иначе gather/loot не смогут ничего дать)
    if (inv.get("free_slots") or 0) <= 0 and (inv.get("junk_count") or 0) > 0:
        return [
            {"subgoal": "GO_TO_VENDOR", "skill": "explore",
             "reason": "bags_full", "target": "vendor"},
            {"subgoal": "SELL", "skill": "sell_junk", "reason": "bags_full"},
        ]

    # 4. READY-квест -> сдать
    if (quest.get("ready") or 0) > 0:
        plan = []
        if (quest.get("giver_distance") or 999.0) > 7.0:
            plan.append({"subgoal": "RETURN_TO_GIVER", "skill": "explore",
                         "reason": "quest_ready", "target": "quest_giver"})
        plan.append({"subgoal": "TURN_IN", "skill": "turn_in_quest",
                     "reason": "quest_ready"})
        return plan

    # 5. активная цель
    nxt = quest.get("next_objective")
    if nxt:
        return _plan_for_objective(nxt, obs)

    # 6. взять новый квест
    if world.get("quest_available"):
        if (quest.get("giver_distance") or 999) > 7.0:
            return [
                {"subgoal": "GO_TO_GIVER", "skill": "explore",
                 "reason": "giver_far", "target": "quest_giver"},
                {"subgoal": "ACCEPT", "skill": "accept_quest",
                 "reason": "quest_available"},
            ]
        return [{"subgoal": "ACCEPT", "skill": "accept_quest",
                 "reason": "quest_available"}]
    if (world.get("quest_givers") or 0) > 0:
        return [
            {"subgoal": "GO_TO_GIVER", "skill": "explore",
             "reason": "giver_far", "target": "quest_giver"},
            {"subgoal": "ACCEPT", "skill": "accept_quest",
             "reason": "quest_available"},
        ]

    # 7. нечего делать -> исследовать (или добить ближайшего моба)
    if (world.get("nearby_mobs") or 0) > 0:
        return [{"subgoal": "FARM", "skill": "farm", "reason": "no_quest"}]
    return [{"subgoal": "EXPLORE", "skill": "explore", "reason": "idle"}]


def _plan_for_objective(objective: Dict[str, Any],
                        obs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Шаги под конкретную цель квеста."""
    otype = (objective.get("type") or "").lower()
    remaining = objective.get("remaining")
    world = obs.get("world") or {}
    plan: List[Dict[str, Any]] = []

    if otype in ("gather", "collect", "item"):
        node_type = objective.get("node_type") or ""
        # collect без node_type = добыча с моба (например, greyjaw_fang).
        # Форсируем farm, а не GO_TO_NODE, иначе агент ищет несуществующую ноду.
        if not node_type and (world.get("nearby_mobs") or 0) > 0:
            # Check if nearest mob is in attack range
            nearest_mob_dist = None
            for m in (obs.get("mobs") or []):
                d = m.get("distance") or m.get("dist")
                if d is not None and (nearest_mob_dist is None or d < nearest_mob_dist):
                    nearest_mob_dist = d
            cls = (obs.get("player") or {}).get("player_class") or ""
            reach = {"warrior": 7.0, "rogue": 7.0, "mage": 27.0,
                     "hunter": 27.0, "priest": 27.0, "warlock": 27.0}.get(cls, 27.0)
            if nearest_mob_dist is not None and nearest_mob_dist > reach:
                plan.append({"subgoal": "APPROACH", "skill": "navigate",
                             "reason": "mob_out_of_range",
                             "target": {"item": objective.get("item_id")}})
            plan.append({"subgoal": "KILL", "skill": "farm",
                         "reason": "objective_collect_mob_drop",
                         "count": remaining,
                         "item": objective.get("item_id")})
            plan.append({"subgoal": "LOOT", "skill": "loot", "reason": "after_kill"})
            return plan
        tool = required_tool(objective)
        if tool and not _has_tool(obs, tool):
            if (world.get("vendor_distance") or 999.0) > 12.0:
                plan.append({"subgoal": "GO_TO_VENDOR", "skill": "explore",
                             "reason": "need_tool", "target": "vendor"})
            plan.append({"subgoal": "GET_TOOL", "skill": "buy",
                         "reason": "need_tool", "item": tool})
        if (world.get("gather_nodes") or 0) == 0:
            plan.append({"subgoal": "GO_TO_NODE", "skill": "explore",
                         "reason": "no_node_in_range",
                         "target": node_type or "node"})
        plan.append({"subgoal": "GATHER", "skill": "gather",
                     "reason": "objective_gather",
                     "count": remaining,
                     "node_type": node_type,
                     "item": objective.get("item_id")})

    elif otype == "kill":
        # No mob visible at all -> search (explore) first. Without this,
        # farm targets nothing and the agent stands still.
        mob_visible = (world.get("nearby_mobs") or 0) > 0
        nearest_mob_dist = None
        for m in (obs.get("mobs") or []):
            d = m.get("distance") or m.get("dist")
            if d is not None and (nearest_mob_dist is None or d < nearest_mob_dist):
                nearest_mob_dist = d
        if nearest_mob_dist is not None:
            mob_visible = True
        if not mob_visible:
            plan.append({"subgoal": "FIND_MOB", "skill": "explore",
                         "reason": "no_mob_in_range",
                         "target_mob_id": objective.get("target_mob_id")})
        else:
            # Mob visible: check if in attack range. If not, force navigate
            # (approach) first — otherwise farm does nothing (bridge only attacks
            # in-range) and agent stands still.
            cls = (obs.get("player") or {}).get("player_class") or ""
            reach = {"warrior": 7.0, "rogue": 7.0, "mage": 27.0,
                     "hunter": 27.0, "priest": 27.0, "warlock": 27.0}.get(cls, 27.0)
            if nearest_mob_dist is not None and nearest_mob_dist > reach:
                plan.append({"subgoal": "APPROACH", "skill": "navigate",
                             "reason": "mob_out_of_range",
                             "target": {"mob_id": objective.get("target_mob_id")}})
        plan.append({"subgoal": "KILL", "skill": "farm",
                     "reason": "objective_kill",
                     "count": remaining,
                     "target_mob_id": objective.get("target_mob_id")})
        plan.append({"subgoal": "LOOT", "skill": "loot", "reason": "after_kill"})

    elif otype in ("craft", "crafting"):
        plan.append({"subgoal": "CRAFT", "skill": "craft",
                     "reason": "objective_craft", "count": remaining})

    elif otype in ("talk", "visit", "deliver"):
        plan.append({"subgoal": "GO_TO_TARGET", "skill": "explore",
                     "reason": "objective_talk"})

    else:
        # неизвестный тип цели: не выдумываем — идём к гиверу и пробуем сдать
        plan.append({"subgoal": "RETURN_TO_GIVER", "skill": "explore",
                     "reason": "unknown_objective_type", "target": "quest_giver"})

    plan.append({"subgoal": "RETURN_TO_GIVER", "skill": "explore",
                 "reason": "objective_done", "target": "quest_giver"})
    plan.append({"subgoal": "TURN_IN", "skill": "turn_in_quest",
                 "reason": "objective_done"})
    return plan


def current_subgoal(obs: Dict[str, Any]) -> Dict[str, Any]:
    """Первый (актуальный сейчас) шаг плана."""
    plan = plan_subgoals(obs)
    return plan[0] if plan else {"subgoal": "EXPLORE", "skill": "explore",
                                 "reason": "empty_plan"}


def _goal_key(obs: Dict[str, Any]) -> str:
    """Стабильный ключ текущего goal для трекинга в памяти."""
    quest = obs.get("quest") or {}
    nxt = quest.get("next_objective") or {}
    if nxt:
        return "quest_obj:%s:%s" % (
            nxt.get("type", ""),
            nxt.get("target_mob_id") or nxt.get("item_id") or
            nxt.get("node_type") or "")
    if quest.get("ready"):
        return "quest_ready"
    if quest.get("active"):
        return "quest_active"
    world = obs.get("world") or {}
    if world.get("quest_available"):
        return "quest_available"
    return "idle"


class Planner:
    """Держит план и min-dwell, чтобы агент не дёргал цель каждый шаг.

    STREAM J3 (memory-aware):
    - При повторном планировании того же goal читает StrategyMemory и
      ExperienceStore, чтобы избегать провальных шаблонов.
    - Логирует planned_step -> result -> lesson.
    """

    def __init__(self, min_dwell: int = 20,
                 strat_mem=None, experience=None):
        self.min_dwell = min_dwell
        self.plan: List[Dict[str, Any]] = []
        self.current: Optional[Dict[str, Any]] = None
        self.dwell = 0
        # STREAM J3: memory access
        self.strat_mem = strat_mem
        self.experience = experience
        # Track failed steps per goal to generate alternatives
        self._failed_steps: Dict[str, List[str]] = {}
        # Track current goal key for memory lookups
        self._current_goal_key: Optional[str] = None
        # Lesson log: list of {step, result, lesson}
        self.lessons: List[Dict[str, str]] = []

    def step(self, obs: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
        """Вернуть актуальный subgoal.

        force=True (смерть, критический HP) перепланирует немедленно,
        игнорируя min_dwell.
        """
        player = obs.get("player") or {}
        hp = player.get("hp_fraction")
        urgent = bool(player.get("dead")) or (hp is not None and hp < 0.35)

        # World-change detection: if the current subgoal is FIND_MOB and
        # mobs appeared, or KILL and mobs disappeared, replan immediately
        # (ignore dwell) so the agent reacts to the world, not the timer.
        world_changed = False
        if self.current and not urgent:
            cur = self.current.get("subgoal")
            nearby = (obs.get("world") or {}).get("nearby_mobs") or 0
            if cur == "FIND_MOB" and nearby > 0:
                world_changed = True
            elif cur == "KILL" and nearby == 0:
                world_changed = True

        if force or urgent or world_changed or self.current is None or self.dwell >= self.min_dwell:
            # STREAM J3: read memory before generating plan
            goal_key = _goal_key(obs)
            self._current_goal_key = goal_key

            # Check if previous plan for this goal had failures
            failed = self._failed_steps.get(goal_key, [])

            self.plan = plan_subgoals(obs)

            # STREAM J3: if previous APPROACH failed, inject alternative
            if "APPROACH" in failed:
                self._inject_alternative_for_failed_approach()

            # STREAM J3: annotate plan with memory-based hints
            self._annotate_with_memory(goal_key)

            self.current = self.plan[0] if self.plan else None
            self.dwell = 0
        else:
            self.dwell += 1
        return self.current or {"subgoal": "EXPLORE", "skill": "explore",
                                "reason": "empty_plan"}

    def force_replan(self) -> None:
        """Сбросить удержание цели: следующий step обязан перепланировать.

        Нужно recovery-ветке abandon/next/replan — иначе min_dwell держал
        отвергнутую цель ещё десятки шагов (P0.7).
        """
        self.current = None
        self.dwell = 0

    def on_subgoal_done(self) -> None:
        """Шаг выполнен: снять его с плана, следующий станет текущим."""
        if self.plan:
            self.plan.pop(0)
        self.current = self.plan[0] if self.plan else None
        self.dwell = 0

    def record_step_outcome(self, subgoal: Dict[str, Any], result: str,
                            reason: str = "") -> None:
        """Записать результат шага для memory-aware planning.

        Вызывается из AutonomyLoop.after_action().
        """
        sg_name = (subgoal or {}).get("subgoal", "")
        goal_key = self._current_goal_key or "unknown"

        # Track failures per goal
        if result == "FAILURE":
            if goal_key not in self._failed_steps:
                self._failed_steps[goal_key] = []
            self._failed_steps[goal_key].append(sg_name)

        # Log lesson
        lesson = {
            "step": sg_name,
            "result": result,
            "reason": reason,
            "goal_key": goal_key,
        }
        self.lessons.append(lesson)

        # Write to StrategyMemory if available
        if self.strat_mem is not None:
            self.strat_mem.record_step(goal_key, sg_name, result == "SUCCESS")

    def reset(self) -> None:
        self.plan = []
        self.current = None
        self.dwell = 0
        self._failed_steps = {}
        self._current_goal_key = None
        self.lessons = []

    # ---- STREAM J3: memory-aware helpers ----

    def _inject_alternative_for_failed_approach(self) -> None:
        """Если APPROACH провалился — заменить на FIND_MOB (обходной путь).

        Вместо повторного подхода к тому же мобу (который уже провалился),
        пробуем найти другого моба того же типа поблизости.
        """
        if not self.plan:
            return
        for i, step in enumerate(self.plan):
            if step.get("subgoal") == "APPROACH":
                # Replace APPROACH with FIND_MOB (search for alternate)
                self.plan[i] = {
                    "subgoal": "FIND_MOB",
                    "skill": "explore",
                    "reason": "approach_failed_alternative",
                    "target_mob_id": step.get("target", {}).get("mob_id"),
                }
                break

    def _annotate_with_memory(self, goal_key: str) -> None:
        """Добавить memory-based hints в текущий план.

        Если StrategyMemory знает успешную стратегию для этого goal —
        добавить hint в первый шаг плана.
        """
        if self.strat_mem is None or not self.plan:
            return
        pref = self.strat_mem.preference(goal_key)
        if pref:
            # Annotate first step with proven strategy hint
            self.plan[0]["_proven_strategy"] = pref
