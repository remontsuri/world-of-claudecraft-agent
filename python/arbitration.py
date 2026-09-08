"""arbitration.py — Priority-ordered decision layer above the policy.

This module contains the decision overrides that were previously embedded in
GoalManager.decide(). It implements the arbitration layer from the unified
decision hierarchy:

  1. SAFETY  → death/critical HP → respawn/heal/noop (safety.py)
  2. RECOVERY → stuck/loop → recovery skill (arbitration_layer.py)
  3. PHASE   → RETURN_TO_GIVER/TURN_IN → navigate to giver
  4. ECONOMY → bags_full → sell_junk (if vendor near)
  5. LOOT    → corpses nearby → loot
  6. POLICY  → softmax over candidates (Q-learning)

Each check returns (action, ctx) if it fires, or None if the decision should
pass to the next lower priority.
"""

from typing import Dict, Optional, Tuple

from policy import (
    SKILL_LOOT,
    SKILL_SELL,
    SKILL_TURN_IN,
    SKILL_RETURN,
)

# Quest turn-in range (INTERACT_RANGE + 2 = 7yd)
QUEST_INTERACT_RANGE = 7.0


def _turn_ctx(info: dict, action: str) -> dict:
    """Ctx for return/turn-in skills: prefer the READY quest."""
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


def _corpses_nearby(info: dict) -> list:
    """Return list of lootable corpses in nearby."""
    near = info.get("nearby") or []
    return [e for e in near
            if (e.get("type") == "corpse" or e.get("kind") == "corpse"
                or ((e.get("kind") == "mob" or e.get("type") == "mob")
                    and (e.get("dead") or e.get("lootable"))))
            and not e.get("looted")]


def _vendor_nearby(info: dict, radius: float = 18.0) -> bool:
    """Return True if a vendor NPC is within radius."""
    ppos = info.get("player_pos") or [0, 0]
    for e in (info.get("nearby") or []):
        if not (e.get("kind") == "npc" or e.get("type") == "npc"):
            continue
        if not (e.get("vendor") or e.get("vendorItems") or e.get("isVendor")):
            continue
        dist = ((e.get("x", 0) - ppos[0]) ** 2 + (e.get("z", 0) - ppos[1]) ** 2) ** 0.5
        if dist <= radius:
            return True
    return False


def _giver_distance(ws: dict) -> Optional[float]:
    """Get distance to quest giver from world state."""
    d = (ws.get("quest") or {}).get("giver_distance")
    if d is None:
        d = ws.get("distance_to_giver")
    return d


def _bag_survival_sell(info: dict, ws: dict, cands: list) -> Optional[Tuple[str, Dict]]:
    """Economy override: bags almost full → sell_junk (if vendor near).

    Server rejects quest turn-in (bagsFullError) if reward doesn't fit.
    Force sell when bag is >= capacity - 3 and vendor is nearby.
    """
    inv = info.get("inventory") or []
    bag_slots = len([s for s in inv if s])
    bag_capacity = ws.get("bag_capacity", 16)
    if bag_slots < bag_capacity - 3:
        return None
    if not _vendor_nearby(info):
        return None

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
            return SKILL_SELL, {"keepIds": list(keep)}
    return None


def _loot_priority(info: dict, ws: dict, cands: list) -> Optional[Tuple[str, Dict]]:
    """Loot override: corpses nearby → loot.

    Softmax rarely picks loot (measured: 1/777 steps), so force it when
    corpses are present and loot is a valid candidate.
    """
    corpses = _corpses_nearby(info)
    if corpses and SKILL_LOOT in cands:
        return SKILL_LOOT, {}
    return None


def _phase_return(info: dict, ws: dict, cands: list) -> Optional[Tuple[str, Dict]]:
    """Phase override: RETURN_TO_GIVER → return_to_giver (if giver far).

    Inside RETURN_TO_GIVER phase the correct skill is deterministic —
    navigate toward the giver. Leaving the choice to softmax let Q-values
    re-derive a farm/heal loop while the ready quest waited.
    """
    if ws.get("hp_frac", 1.0) < 0.35:
        return None  # survival gate: don't walk when hurt
    if SKILL_RETURN in cands:
        return SKILL_RETURN, _turn_ctx(info, SKILL_RETURN)
    return None


def _turn_in_phase(info: dict, ws: dict, cands: list) -> Optional[Tuple[str, Dict]]:
    """Phase override: TURN_IN → turn_in (if giver close) or return (if far).

    Turn-in only succeeds within QUEST_INTERACT_RANGE (7yd). If giver is farther,
    must navigate closer first.
    """
    d = _giver_distance(ws)
    if d is None:
        return None
    if d > QUEST_INTERACT_RANGE and SKILL_RETURN in cands:
        return SKILL_RETURN, _turn_ctx(info, SKILL_RETURN)
    if SKILL_TURN_IN in cands:
        return SKILL_TURN_IN, _turn_ctx(info, SKILL_TURN_IN)
    return None


def arbitrate(
    info: dict,
    ws: dict,
    phase: str,
    cands: list,
    tool_need: Optional[str] = None,
    buy_state: Optional[dict] = None,
    step_idx: int = 0,
    world_mem=None,
) -> Optional[Tuple[str, Dict]]:
    """Run priority-ordered arbitration checks.

    Returns (action, ctx) from the first matching check, or None if no
    override fires (policy decides via softmax).

    Args:
        info: Raw info dict from the bridge.
        ws: World state dict.
        phase: Current FSM phase string.
        cands: Candidate skills from policy._candidates().
        tool_need: Item ID needed for gather quest (from ws["needs_tool"]).
        buy_state: Dict with fails/cooldown for tool priority cooldown.
        step_idx: Current step index for cooldown check.
        world_mem: WorldMemory instance for vendor positions.

    Returns:
        (action, ctx) if an override fires, None otherwise.
    """
    # 1. Plan-stack: READY quest at giver (dist<=6) → turn_in immediately
    if (ws.get("quest_status") == "READY_TO_TURN_IN"
            and ws.get("quest", {}).get("giver_distance", 999) <= 6):
        ctx = {}
        qid = ws.get("quest", {}).get("id")
        if qid:
            ctx["questId"] = qid
            ctx["quest"] = {"id": qid}
        return SKILL_TURN_IN, ctx

    # 2. Tool priority: gather quest needs tool → buy (with cooldown)
    if tool_need:
        has_tool = any(
            s.get("itemId") == tool_need
            for s in (info.get("inventory") or [])
        )
        if not has_tool and buy_state is not None:
            if step_idx >= buy_state.get("cooldown_until_step", -1):
                ctx = {"buyItemId": tool_need}
                if world_mem is not None:
                    vendor = world_mem.vendor_pos("trader_wilkes")
                    if vendor:
                        ctx["vendorPos"] = vendor
                return "buy", ctx

    # 3. Bag survival: bags almost full → sell_junk (if vendor near)
    result = _bag_survival_sell(info, ws, cands)
    if result is not None:
        return result

    # 4. Loot priority: corpses nearby → loot
    if phase in ("DO_OBJECTIVE", "RETURN_TO_GIVER", "TURN_IN"):
        result = _loot_priority(info, ws, cands)
        if result is not None:
            return result

    # 5. Phase return: RETURN_TO_GIVER → return_to_giver
    if phase == "RETURN_TO_GIVER":
        result = _phase_return(info, ws, cands)
        if result is not None:
            return result

    # 6. Turn-in phase: TURN_IN → turn_in or return
    if phase == "TURN_IN":
        result = _turn_in_phase(info, ws, cands)
        if result is not None:
            return result

    return None
