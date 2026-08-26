"""planner.py — Planner выше PPO (ARCHITECTURE.md §5).

PPO не должен с нуля выучивать смысл игры. Planner раскладывает objective
квеста в последовательность subgoal-ов, а политика выбирает КАК выполнить
текущий subgoal.

    QUEST: collect 8 ironbark
      -> GET_TOOL -> GO_TO_NODE -> GATHER xN -> RETURN_TO_GIVER -> TURN_IN

План — данные (список шагов). Planner не трогает игру и не решает,
какое действие послать в мост: он говорит, какой шаг сейчас актуален.
"""
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
        return [{"subgoal": "RESPAWN", "skill": "heal", "reason": "player_dead"}]

    # 2. критический HP
    hp = player.get("hp_fraction")
    if hp is not None and hp < 0.35:
        return [{"subgoal": "SURVIVE", "skill": "heal", "reason": "hp_critical"}]

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
        tool = required_tool(objective)
        if tool and not _has_tool(obs, tool):
            # инструмент ДО выхода из города — иначе gather будет молча падать
            if (world.get("vendor_distance") or 999.0) > 12.0:
                plan.append({"subgoal": "GO_TO_VENDOR", "skill": "explore",
                             "reason": "need_tool", "target": "vendor"})
            plan.append({"subgoal": "GET_TOOL", "skill": "buy",
                         "reason": "need_tool", "item": tool})
        if (world.get("gather_nodes") or 0) == 0:
            plan.append({"subgoal": "GO_TO_NODE", "skill": "explore",
                         "reason": "no_node_in_range",
                         "target": objective.get("node_type") or "node"})
        plan.append({"subgoal": "GATHER", "skill": "gather",
                     "reason": "objective_gather",
                     "count": remaining,
                     "node_type": objective.get("node_type"),
                     "item": objective.get("item_id")})

    elif otype == "kill":
        if (world.get("nearby_mobs") or 0) == 0:
            plan.append({"subgoal": "FIND_MOB", "skill": "explore",
                         "reason": "no_mob_in_range",
                         "target": objective.get("target_mob_id")})
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


class Planner:
    """Держит план и min-dwell, чтобы агент не дёргал цель каждый шаг."""

    def __init__(self, min_dwell: int = 20):
        self.min_dwell = min_dwell
        self.plan: List[Dict[str, Any]] = []
        self.current: Optional[Dict[str, Any]] = None
        self.dwell = 0

    def step(self, obs: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
        """Вернуть актуальный subgoal.

        force=True (смерть, критический HP) перепланирует немедленно,
        игнорируя min_dwell.
        """
        player = obs.get("player") or {}
        hp = player.get("hp_fraction")
        urgent = bool(player.get("dead")) or (hp is not None and hp < 0.35)

        if force or urgent or self.current is None or self.dwell >= self.min_dwell:
            self.plan = plan_subgoals(obs)
            self.current = self.plan[0] if self.plan else None
            self.dwell = 0
        else:
            self.dwell += 1
        return self.current or {"subgoal": "EXPLORE", "skill": "explore",
                                "reason": "empty_plan"}

    def on_subgoal_done(self) -> None:
        """Шаг выполнен: снять его с плана, следующий станет текущим."""
        if self.plan:
            self.plan.pop(0)
        self.current = self.plan[0] if self.plan else None
        self.dwell = 0

    def reset(self) -> None:
        self.plan = []
        self.current = None
        self.dwell = 0
