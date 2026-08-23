"""GoalFSM — explicit finite-state machine for the agent's current objective.

Why this exists (per user 2026-08-20): the old GoalManager picked a raw skill
from a flat candidate list every step. There was NO field saying "which phase
of the quest am I in", so the agent re-decided globally each step and could
never chain accept -> objective -> return -> turn_in as ONE plan.

This module makes the goal EXPLICIT and PERSISTENT:
  - current_goal is a string (NO_QUEST / FIND_GIVER / ACCEPT / DO_OBJECTIVE /
    RETURN_TO_GIVER / TURN_IN / SELL_REPAIR / HEAL / RESPAWN / DEAD).
  - It is saved to goal_state.json so an infrastructure restart does NOT wipe
    an in-progress quest (the agent resumes from PREVIOUS_GOAL, not NO_QUEST).
  - The Policy chooses a SKILL *within* the current goal, not a global action.

Death is a sub-state: ANY_STATE -> DEAD -> GO_TO_SPIRIT_HEALER -> RESPAWN ->
RECOVER -> PREVIOUS_GOAL. Death does NOT destroy the goal.

Transitions are driven by OBSERVED facts (quest status from the bridge), not by
hard-coded rules about "what to do". The FSM only answers "where am I in the
quest lifecycle"; the Policy answers "which skill now".
"""

import json
import os
import time
import tempfile
import traceback
from typing import Optional


# ---- goal state constants ----------------------------------------------------
NO_QUEST        = "NO_QUEST"
FIND_GIVER      = "FIND_GIVER"
ACCEPT          = "ACCEPT"
DO_OBJECTIVE     = "DO_OBJECTIVE"
RETURN_TO_GIVER = "RETURN_TO_GIVER"
TURN_IN         = "TURN_IN"
SELL_REPAIR     = "SELL_REPAIR"
HEAL            = "HEAL"
RESPAWN         = "RESPAWN"
DEAD            = "DEAD"

# Quest lifecycle (forward path)
QUEST_CYCLE = [NO_QUEST, FIND_GIVER, ACCEPT, DO_OBJECTIVE, RETURN_TO_GIVER, TURN_IN]

# Goals that represent "a quest is active and being worked on" — used to decide
# whether the agent should keep progressing the quest instead of free-roaming.
ACTIVE_GOALS = {FIND_GIVER, ACCEPT, DO_OBJECTIVE, RETURN_TO_GIVER, TURN_IN}


class GoalFSM:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(os.path.dirname(__file__), "goal_state.json")
        # current goal
        self.goal = NO_QUEST
        # the quest we are working on (id), so we can resume after restart
        self.quest_id: Optional[str] = None
        # previous goal before death (to resume after respawn)
        self.pre_death_goal: Optional[str] = None
        # monotonic step counter for persistence bookkeeping
        self.updated_at: float = 0.0
        self._load()

    # ---- persistence (survives infra restart) ----
    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.goal = d.get("goal", NO_QUEST)
            self.quest_id = d.get("quest_id")
            self.pre_death_goal = d.get("pre_death_goal")
            self.updated_at = d.get("updated_at", 0.0)
        except Exception:
            return  # corrupt -> fresh FSM

    def save(self):
        try:
            d = os.path.dirname(os.path.abspath(self.path)) or "."
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".goal_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({
                    "goal": self.goal,
                    "quest_id": self.quest_id,
                    "pre_death_goal": self.pre_death_goal,
                    "updated_at": time.time(),
                }, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)  # atomic on Windows
        except Exception:
            traceback.print_exc()

    # ---- transitions ----
    def set(self, goal: str, quest_id: Optional[str] = None):
        if quest_id is not None:
            self.quest_id = quest_id
        if self.goal != goal or (quest_id is not None):
            self.goal = goal
            self.save()

    def enter_dead(self):
        """Called when the character dies. Preserve the pre-death goal."""
        if self.goal != DEAD:
            self.pre_death_goal = self.goal if self.goal != DEAD else self.pre_death_goal
            self.goal = DEAD
            self.save()

    def resume_after_respawn(self):
        """After respawn, return to the goal we had before death."""
        prev = self.pre_death_goal or (self.quest_id and DO_OBJECTIVE) or NO_QUEST
        self.goal = prev
        self.pre_death_goal = None
        self.save()

    def reset_to_no_quest(self):
        self.goal = NO_QUEST
        self.quest_id = None
        self.pre_death_goal = None
        self.save()

    # ---- fact-driven transition (called each step with observed world) ----
    def update_from_world(self, ws: dict):
        """Move the FSM based on OBSERVED quest facts.

        `ws` is the structured WorldState (see world_state.py extension):
          ws["quest"] = {
            "id", "phase" (NO_QUEST/ACTIVE/READY), "accepted": bool,
            "progress": int, "required": int, "complete": bool,
            "giver_known": bool, "giver_distance": float
          }
        Death is handled separately (enter_dead / resume_after_respawn).

        This only sets the goal; it does NOT pick a skill. That is the Policy's
        job, which reads self.goal to constrain its candidate set.
        """
        q = ws.get("quest") or {}
        qphase = q.get("phase", "NONE")
        # If we are in the middle of death handling, don't override.
        if self.goal == DEAD:
            return

        if qphase == "NONE" or not q.get("id"):
            # No active quest -> look for one to start.
            if self.goal in ACTIVE_GOALS:
                # Quest we were working on disappeared (turned in or dropped).
                self.reset_to_no_quest()
            else:
                self.set(NO_QUEST)
            return

        # We have a quest. Track its id.
        # R1 FIX (2026-08-23 stall): validate a persisted goal against the OLD
        # tracked quest BEFORE re-pointing. After an infra restart the FSM can
        # wake up as TURN_IN/q_old while the live world shows q_new ACTIVE —
        # silently re-pointing kept TURN_IN forever and pinned policy to the
        # [turn_in_quest, return_to_giver] pocket (measured run: 1860 return +
        # 1140 turn_in, nothing else).
        tracked = self.quest_id
        if (self.goal == TURN_IN and q.get("id")
                and tracked and q.get("id") != tracked):
            # The quest we were turning in is GONE from the live log; the
            # observed ACTIVE quest is a different one. Work its objective.
            self.set(DO_OBJECTIVE, q.get("id"))
            return

        # Fix5 (2026-08-23 live run): SAME quest id but observed ACTIVE with
        # incomplete objectives under a TURN_IN goal — the turn-in already
        # happened or the objective regressed; the goal is stale. Demote to
        # DO_OBJECTIVE. (Measured: 700+ steps farming under TURN_IN because the
        # phase gate offered no candidates and the full-list fallback fired.)
        if (self.goal == TURN_IN and qphase == "ACTIVE"
                and not q.get("complete", True)):
            self.set(DO_OBJECTIVE, q.get("id"))
            return

        if self.quest_id != q.get("id"):
            self.quest_id = q.get("id")

        if qphase == "READY":
            # Objectives done, awaiting turn-in.
            if self.goal in (RETURN_TO_GIVER, TURN_IN, DO_OBJECTIVE):
                self.set(TURN_IN, q.get("id"))
            elif self.goal == NO_QUEST or self.goal == FIND_GIVER:
                self.set(RETURN_TO_GIVER, q.get("id"))
            return

        # qphase == "ACTIVE": objectives still in progress.
        if self.goal in (NO_QUEST, FIND_GIVER):
            self.set(DO_OBJECTIVE, q.get("id"))
        elif self.goal == ACCEPT:
            self.set(DO_OBJECTIVE, q.get("id"))
        elif self.goal == RETURN_TO_GIVER:
            # 2026-08-23: keep RETURN_TO_GIVER while a READY quest waits — turning
            # it in is the correct move even if the ws-selected quest shows ACTIVE
            # objectives (the ready quest lives in a parallel bucket). Only demote
            # when nothing is ready.
            if not ws.get("has_ready"):
                self.set(DO_OBJECTIVE, q.get("id"))
        # DO_OBJECTIVE / TURN_IN stay as-is (TURN_IN only set when READY).

    def is_active(self) -> bool:
        return self.goal in ACTIVE_GOALS

    def __repr__(self):
        return f"GoalFSM(goal={self.goal}, quest={self.quest_id})"
