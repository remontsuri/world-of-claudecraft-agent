"""quest_objective.py — Objective resolution and dispatch.

Maps quest objectives (kill/collect/gather/craft/escort) to concrete targets
and the skills that advance them. No orchestration — just deterministic
resolution from game facts.
"""
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any


class ObjectiveType(Enum):
    KILL = "kill"
    COLLECT = "collect"
    GATHER = "gather"
    CRAFT = "craft"
    ESCORT = "escort"


@dataclass
class Objective:
    type: ObjectiveType
    target_mob_id: Optional[str] = None
    item_id: Optional[str] = None
    node_type: Optional[str] = None
    current: int = 0
    required: int = 0
    tool_item_id: Optional[str] = None


def resolve_objective(quest: dict, info: dict = None) -> Optional[Objective]:
    """Resolve the first incomplete objective of a quest.

    Returns None when all objectives are complete (or the quest has none).
    """
    objectives = quest.get("objectives") or []
    for o in objectives:
        current = o.get("current") or 0
        required = o.get("required") or 0
        if current >= required:
            continue
        obj_type = o.get("type", "kill")
        target_mob_id = o.get("targetMobId") or o.get("mobId") or o.get("targetId")
        item_id = o.get("itemId")
        node_type = o.get("nodeType")
        tool_item_id = o.get("toolItemId") or o.get("requiredToolId") or o.get("toolId")
        try:
            otype = ObjectiveType(obj_type)
        except ValueError:
            otype = ObjectiveType.KILL  # default fallback
        return Objective(
            type=otype,
            target_mob_id=str(target_mob_id) if target_mob_id else None,
            item_id=str(item_id) if item_id else None,
            node_type=str(node_type) if node_type else None,
            current=current,
            required=required,
            tool_item_id=str(tool_item_id) if tool_item_id else None,
        )
    return None


def resolve_target(objective: Objective, info: dict) -> Optional[dict]:
    """Find the target entity for an objective in the nearby scan."""
    nearby = info.get("nearby") or []

    if objective.type == ObjectiveType.KILL:
        # Match mob by templateId
        for e in nearby:
            if e.get("kind") != "mob" and e.get("type") != "mob":
                continue
            template = e.get("templateId") or e.get("mobId") or e.get("name")
            if template and objective.target_mob_id and str(template) == str(objective.target_mob_id):
                return e
        # Fallback: any hostile mob
        for e in nearby:
            if (e.get("kind") == "mob" or e.get("type") == "mob") and e.get("hostile") is not False:
                return e
        return None

    if objective.type == ObjectiveType.COLLECT:
        # Collect from mob drops — find any mob
        for e in nearby:
            if e.get("kind") == "mob" or e.get("type") == "mob":
                return e
        return None

    if objective.type == ObjectiveType.GATHER:
        for e in nearby:
            if e.get("kind") == "node" or e.get("type") == "node":
                if objective.node_type is None or e.get("nodeType") == objective.node_type:
                    return e
        return None

    if objective.type == ObjectiveType.CRAFT:
        for e in nearby:
            if e.get("kind") == "station" or e.get("type") == "station":
                return e
        return None

    if objective.type == ObjectiveType.ESCORT:
        for e in nearby:
            if e.get("kind") == "npc" or e.get("type") == "npc":
                return e
        return None

    return None


def dispatch_objective(objective: Objective, target: dict, env, ctx: dict) -> str:
    """Execute one step toward the objective. Returns verdict string."""
    if objective.type == ObjectiveType.KILL:
        env.step(0)  # farm
        return "PARTIAL"

    if objective.type == ObjectiveType.COLLECT:
        env.step(0)  # farm to kill
        corpses = [e for e in (env._last_info.get("nearby") or [])
                   if (e.get("type") == "corpse" or e.get("lootable")) and not e.get("looted")]
        if corpses:
            env.step(1)  # loot
        return "PARTIAL"

    if objective.type == ObjectiveType.GATHER:
        env.step(5)  # gather
        return "PARTIAL"

    if objective.type == ObjectiveType.CRAFT:
        env.step(6)  # craft
        return "PARTIAL"

    if objective.type == ObjectiveType.ESCORT:
        env.step(0)  # move with escort NPC
        return "PARTIAL"

    return "FAILURE"
