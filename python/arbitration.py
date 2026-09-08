"""arbitration.py — Single decision point for the agent.

Priority-ordered decision flow:
1. Safety (death, critical HP) — safety.py
2. Recovery (loop, stuck, pending_recovery) — recovery.py + anti_loop.py
3. FSM sync (read-only phase label) — goal_fsm.py
4. Planner advisor (subgoal context) — planner.py
5. Candidate filtering (phase + preconditions + blacklist) — policy.py + anti_loop.py
6. Policy softmax (Q-learning) — policy.py

Replaces AutonomyLoop.before_action() which had conflicting force logic.
"""

from typing import Optional, Tuple, Dict, Any, List

from safety import safety_check


# ---- Legacy override functions (kept for backward compatibility with policy.py) ----

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
        if (q.get("turnInpc") or {}).get("x") is not None:
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
    """Economy override: bags almost full -> sell_junk (if vendor near)."""
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
    """Loot override: corpses nearby -> loot."""
    corpses = _corpses_nearby(info)
    if corpses and SKILL_LOOT in cands:
        return SKILL_LOOT, {}
    return None


def _phase_return(info: dict, ws: dict, cands: list) -> Optional[Tuple[str, Dict]]:
    """Phase override: RETURN_TO_GIVER -> return_to_giver (if giver far)."""
    if ws.get("hp_frac", 1.0) < 0.35:
        return None  # survival gate: don't walk when hurt
    if SKILL_RETURN in cands:
        return SKILL_RETURN, _turn_ctx(info, SKILL_RETURN)
    return None


def _turn_in_phase(info: dict, ws: dict, cands: list) -> Optional[Tuple[str, Dict]]:
    """Phase override: TURN_IN -> turn_in (if giver close) or return (if far)."""
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

    Legacy function — kept for backward compatibility with policy.py.
    New code should use ArbitrationLayer.decide() instead.
    """
    # 1. Plan-stack: READY quest at giver (dist<=6) -> turn_in immediately
    if (ws.get("quest_status") == "READY_TO_TURN_IN"
            and ws.get("quest", {}).get("giver_distance", 999) <= 6):
        ctx = {}
        qid = ws.get("quest", {}).get("id")
        if qid:
            ctx["questId"] = qid
            ctx["quest"] = {"id": qid}
        return SKILL_TURN_IN, ctx

    # 2. Tool priority: gather quest needs tool -> buy (with cooldown)
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

    # 3. Bag survival: bags almost full -> sell_junk (if vendor near)
    result = _bag_survival_sell(info, ws, cands)
    if result is not None:
        return result

    # 4. Loot priority: corpses nearby -> loot
    if phase in ("DO_OBJECTIVE", "RETURN_TO_GIVER", "TURN_IN"):
        result = _loot_priority(info, ws, cands)
        if result is not None:
            return result

    # 5. Phase return: RETURN_TO_GIVER -> return_to_giver
    if phase == "RETURN_TO_GIVER":
        result = _phase_return(info, ws, cands)
        if result is not None:
            return result

    # 6. Turn-in phase: TURN_IN -> turn_in or return
    if phase == "TURN_IN":
        result = _turn_in_phase(info, ws, cands)
        if result is not None:
            return result

    return None


# ---- New ArbitrationLayer (Phase 5) ----

class ArbitrationLayer:
    """Single decision point for the agent.

    Priority-ordered decision flow:
      1. Safety (death, critical HP)
      2. Recovery (loop, stuck, pending_recovery)
      3. FSM sync (read-only phase label)
      4. Planner advisor (subgoal context)
      5. Candidate filtering (phase + preconditions + blacklist)
      6. Policy softmax (Q-learning)

    Replaces AutonomyLoop.before_action() which had conflicting force logic.
    """

    def __init__(self, fsm, planner, recovery_tracker, loop_guard, blacklist,
                 autonomy=None):
        self.fsm = fsm
        self.planner = planner
        self.recovery = recovery_tracker
        self.guard = loop_guard
        self.blacklist = blacklist
        self.autonomy = autonomy  # Reference to AutonomyLoop for pending_recovery

    def decide(self, info: dict, ws: dict, policy: 'GoalManager') -> Tuple[str, dict, str]:
        """Return (action, ctx, reason).

        reason: "safety" | "recovery" | "policy" | "fallback"
        """
        # 1. SAFETY — death/critical HP
        forced = safety_check(info, ws)
        if forced:
            return forced, {}, "safety"

        # 2. RECOVERY — pending recovery from after_action()
        if self.autonomy is not None and self.autonomy.pending_recovery:
            pend = self.autonomy.pending_recovery
            self.autonomy.pending_recovery = None
            if self.autonomy is not None:
                self.autonomy.stats["recoveries_executed"] = \
                    self.autonomy.stats.get("recoveries_executed", 0) + 1
            if pend["kind"] == "skill":
                sk = pend["skill"]
                return sk, {"reason": "recovery_action", "recovery": pend}, "recovery"
            elif pend["kind"] == "navigate":
                # Navigation is handled by the runner, not the policy
                # Return explore as fallback; runner will handle nav
                return "explore", {"reason": "recovery_navigate", "target": pend.get("target")}, "recovery"

        # 2b. RECOVERY — loop detection
        if self.guard.is_looping():
            trip = self.guard.trip()
            action_name = trip.get("action", "explore")
            rec = self.recovery.next_action(action_name, "loop_detected", ws)
            if rec:
                from autonomy import RECOVERY_TO_SKILL
                skill = RECOVERY_TO_SKILL.get(rec.get("recovery_action"))
                if skill:
                    return skill, {"reason": "loop_recovery", "trip": trip}, "recovery"

        # 3. FSM SYNC (read-only)
        self.fsm.update_from_world(ws)
        phase = self.fsm.phase

        # 4. PLANNER ADVISOR
        from observation import encode_observation
        obs = encode_observation(ws, info)
        advisor = self.planner.advisor_context(obs)

        # 5. CANDIDATE FILTERING
        cands = policy._candidates(info, ws, phase=phase, advisor=advisor)
        cands = self.guard.filter_candidates(cands)

        # Blacklist check — remove blocked objectives
        objective_key = self._objective_key(ws)
        if objective_key and self.blacklist.is_blocked(objective_key):
            current_skill = (self.planner.current or {}).get("skill")
            cands = [c for c in cands if c != current_skill]

        if not cands:
            return "explore", {}, "fallback"

        # 6. POLICY SOFTMAX
        action, ctx = policy.decide(info, ws, phase=phase, advisor=advisor, allowed=cands)
        return action, ctx, "policy"

    @staticmethod
    def _objective_key(ws: dict) -> Optional[str]:
        """Stable key for current objective (for blacklist)."""
        q = (ws or {}).get("quest") or {}
        nxt = q.get("next_objective") or {}
        if nxt:
            return "%s:%s:%s" % (nxt.get("quest_id"), nxt.get("type"),
                                 nxt.get("target_mob_id") or nxt.get("item_id")
                                 or nxt.get("node_type") or "")
        return None
