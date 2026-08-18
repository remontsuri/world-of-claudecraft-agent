"""QuestCapability — thin, script-free wrappers over the existing capability API.

Per user 2026-08-16 + woc-hierarchical-agent skill: this is NOT an orchestrator.
It only EXPOSES capabilities the QuestSkill (or any skill) can call:
  find_quest / accept / get_objectives / navigate_to / check_progress / turn_in.
Each returns SUCCESS / PARTIAL / FAILURE so a higher policy can decide what to do
with the result. No `if ready: return_to_npc` logic lives here — that's the agent's
job to learn.
"""

from typing import Optional


class QuestCapability:
    def __init__(self, env):
        self.env = env

    # ---- read world state (no mutation) ----
    def find_active_quest(self) -> Optional[dict]:
        active = self.env._last_info.get("quests", {}).get("active", []) or []
        for q in active:
            st = q.get("state")
            if st in ("active", "ready", "complete"):
                return q
        return None

    def find_available_quest_npc(self) -> Optional[dict]:
        """An NPC near the player that offers a quest (has non-empty questIds)."""
        near = self.env._last_info.get("nearby") or []
        for e in near:
            qids = e.get("questIds") or e.get("questId")
            if (e.get("kind") == "npc" or e.get("type") == "npc") and qids:
                return e
        return None

    def get_objectives(self, q: dict) -> list:
        return q.get("objectives") or []

    def incomplete_objective(self, q: dict) -> Optional[dict]:
        for o in self.get_objectives(q):
            if (o.get("current") or 0) < (o.get("required") or 0):
                return o
        return None

    def quest_status(self, q: dict) -> str:
        """Observable fact for the policy — NOT a trigger."""
        if q is None:
            return "NONE"
        st = q.get("state")
        if st in ("ready", "complete"):
            return "READY_TO_TURN_IN"
        # active but objective filled?
        if self.incomplete_objective(q) is None:
            return "READY_TO_TURN_IN"
        return "ACTIVE"

    def check_progress(self, q: dict) -> dict:
        """Return current/required per objective (server-authoritative counts)."""
        out = []
        for o in self.get_objectives(q):
            out.append({
                "type": o.get("type"),
                "target": o.get("targetMobId") or o.get("itemId"),
                "current": o.get("current"),
                "required": o.get("required"),
            })
        return {"quest_id": q.get("id"), "objectives": out}

    # ---- mutating capabilities (thin calls to the server) ----
    def accept(self, qid: str) -> str:
        try:
            out = self.env.base.accept_quest(str(qid))
            self.env._last_info = out
            return "SUCCESS"
        except Exception:
            return "FAILURE"

    def navigate_to_turn_in(self, q: dict) -> str:
        """Walk to the turn-in NPC. Returns SUCCESS if within interact range.

        Uses SHORT navigation only (the anti-crash contract): if a navPath is
        present (server A*, maxSpan>=256) use it; else short _navigate_to_coord.
        No long-distance A* (it crashes the headless server)."""
        tNpc = q.get("turnInNpc") or {}
        if tNpc.get("x") is None:
            return "FAILURE"
        if tNpc.get("navPath"):
            ok = self.env._navigate_along_path(tNpc["navPath"], max_steps_per_leg=80)
        else:
            ok = self.env._navigate_to_coord(tNpc["x"], tNpc["z"], max_steps=80)
        return "SUCCESS" if ok else "PARTIAL"

    def turn_in(self, q: dict) -> str:
        qid = str(q.get("id"))
        try:
            out = self.env.base.turn_in_quest(qid)
            self.env._last_info = out
            in_done = qid in (out.get("quests", {}).get("done", []) or [])
            return "SUCCESS" if in_done else "PARTIAL"
        except Exception:
            return "FAILURE"


def quest_state_for_policy(info: dict) -> str:
    """Helper: best active-quest status string for the WorldState."""
    qc = QuestCapability(None)
    # build a dummy to reuse logic without an env
    class _S:
        _last_info = info
    qc.env = _S()
    q = qc.find_active_quest()
    return qc.quest_status(q)
