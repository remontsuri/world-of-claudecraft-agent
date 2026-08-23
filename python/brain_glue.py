"""Glue between the LLM brain and the GoalFSM.

Kept import-light ON PURPOSE: tests import this module directly, and it must
not drag browser_env/agent with it. play_autonomous imports from here.
"""
from llm_brain import GOALS

# The FSM has no SURVIVE state — death handling lives outside decide().
_GOAL_MAP = {"SURVIVE": "HEAL"}


def build_brain_payload(ws: dict, info: dict, fsm_quest_id) -> dict:
    """Compact world JSON for the LLM: only what a strategist needs."""
    q = dict(ws.get("quest") or {})
    if fsm_quest_id:
        q["id"] = fsm_quest_id
    # Fix (2026-08-23): the brain must SEE ready quests — without this it can
    # never choose TURN_IN (measured: 492 steps, 0 turn-in attempts, the ready
    # quest invisible in the payload).
    ready_quests = []
    for rq in ((info.get("quests") or {}).get("ready") or []):
        prog, req = 0, 0
        for o in (rq.get("objectives") or []):
            prog += min(o.get("current") or 0, o.get("required") or 0)
            req += o.get("required") or 0
        ready_quests.append({"id": rq.get("id"),
                             "progress": prog, "required": req})
    return {
        "ready_quests": ready_quests,
        "quest": {
            "id": q.get("id"),
            "phase": q.get("phase"),
            "progress": q.get("progress"),
            "required": q.get("required"),
        },
        "giver_distance": q.get("giver_distance", ws.get("distance_to_giver")),
        "player": {
            "hp_frac": ws.get("hp_frac"),
            "dead": bool((info.get("player") or {}).get("dead")),
        },
        "bag_slots": len([s for s in (info.get("inventory") or []) if s]),
    }


def apply_decision(fsm, decision) -> bool:
    """Apply an LLM {goal, reason} to the FSM. Returns True if applied.

    Invalid/absent decisions leave the FSM untouched (fallback = plain FSM+Q).
    """
    if not isinstance(decision, dict):
        return False
    goal = decision.get("goal")
    if goal not in GOALS:
        return False
    goal = _GOAL_MAP.get(goal, goal)
    fsm.set(goal, fsm.quest_id)
    return True
