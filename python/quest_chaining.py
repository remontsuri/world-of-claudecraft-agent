"""quest_chaining.py — Post-turn-in quest chaining.

After a quest is turned in, find the next available quest giver
(never re-accept a quest already in done_ids).
"""
from typing import Optional, Dict, List, Set


def filter_done_quests(npcs: List[dict], done_ids: Set[str]) -> List[dict]:
    """Filter NPCs to those with at least one non-done quest."""
    result = []
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        quest_ids = npc.get("questIds") or []
        available = [qid for qid in quest_ids if str(qid) not in done_ids]
        if available:
            result.append({**npc, "_available_quests": available})
    return result


def select_best_quest(givers: List[dict]) -> Optional[dict]:
    """Select the best quest from candidates (closest, lowest distance)."""
    if not givers:
        return None
    givers.sort(key=lambda g: g.get("dist") or g.get("distance") or 999)
    best = givers[0]
    available = best.get("_available_quests") or best.get("questIds") or []
    return {
        "npc": best,
        "quest_id": str(available[0]) if available else None,
        "quest_ids": [str(q) for q in available],
    }


def find_next_quest(info: dict, done_ids: Set[str]) -> Optional[dict]:
    """Find the next available quest giver, excluding done quests.

    Priority:
      1. NPC with questIds where at least one quest is NOT in done_ids
      2. Prefer closest NPC (by distance)
      3. Prefer NPC with most available quests

    Returns: {"npc": npc_info, "quest_id": str, "quest_ids": list} or None.
    """
    nearby = info.get("nearby") or []
    npcs = [e for e in nearby if isinstance(e, dict)
             and (e.get("kind") == "npc" or e.get("type") == "npc")
             and (e.get("questIds") or e.get("questId"))]
    candidates = filter_done_quests(npcs, done_ids)
    if not candidates:
        return None
    return select_best_quest(candidates)
