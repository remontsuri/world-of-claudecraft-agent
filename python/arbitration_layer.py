"""arbitration_layer.py — Decision logic separate from FSM state tracking.

This module contains the decision logic that was previously embedded in
GoalFSM.decide(). It answers "what should I do?" based on:
  - The current FSM state (what state am I in?)
  - The world state (what's happening around me?)
  - Safety constraints (am I about to die?)

The FSM itself only tracks quest state and answers "what state am I in?".
This layer decides what action to take given that state.

Architecture:
    Observation -> FSM (state tracking) -> ArbitrationLayer (decision) -> Action
                                       -> SafetyLayer (override) -> Action
"""

from typing import Dict, Optional, Tuple

from goal_fsm import QuestState, INTERACT_RANGE

# Action names returned by the arbitration layer
ACTION_EXPLORE = "explore"
ACTION_NAVIGATE = "navigate"
ACTION_ACCEPT_QUEST = "accept_quest"
ACTION_TURN_IN_QUEST = "turn_in_quest"
ACTION_FARM = "farm"
ACTION_HEAL = "heal"


class ArbitrationLayer:
    """Decides what action to take given the current FSM state and world.

    This is a pure decision layer — it does NOT modify FSM state.
    The FSM state is updated separately via fsm.update_from_world().
    """

    def decide(self, fsm, world_state: dict, info: dict) -> Tuple[str, Dict]:
        """Decide the next action based on FSM state and world observation.

        Args:
            fsm: The GoalFSM instance (read-only access to state).
            world_state: Current world state dict.
            info: Additional info (nearby entities, player data).

        Returns:
            (action_name, ctx) — the action for the Skill Layer to execute.
        """
        state = fsm.state

        # Dispatch based on FSM state
        if state == QuestState.QUEST_NONE:
            return self._handle_quest_none(fsm, world_state, info)
        elif state == QuestState.FIND_GIVER:
            return self._handle_find_giver(fsm, world_state, info)
        elif state == QuestState.ACCEPT:
            return self._handle_accept(fsm, world_state, info)
        elif state == QuestState.VERIFY_ACCEPT:
            return self._handle_verify_accept(fsm, world_state, info)
        elif state == QuestState.DO_OBJECTIVE:
            return self._handle_do_objective(fsm, world_state, info)
        elif state == QuestState.VERIFY_PROGRESS:
            return self._handle_verify_progress(fsm, world_state, info)
        elif state == QuestState.RETURN_TO_GIVER:
            return self._handle_return_to_giver(fsm, world_state, info)
        elif state == QuestState.TURN_IN:
            return self._handle_turn_in(fsm, world_state, info)
        elif state == QuestState.VERIFY_TURN_IN:
            return self._handle_verify_turn_in(fsm, world_state, info)
        elif state == QuestState.RESPAWN:
            return self._handle_respawn(fsm, world_state, info)
        elif state == QuestState.DONE:
            return self._handle_done(fsm, world_state, info)
        elif state == QuestState.ERROR:
            return self._handle_error(fsm, world_state, info)
        else:
            return ACTION_EXPLORE, {"reason": "unknown_state"}

    def _handle_quest_none(self, fsm, ws: dict, info: dict) -> Tuple[str, Dict]:
        """No active quest — find a quest giver with available quests."""
        nearby = info.get("nearby", []) or []
        # Get completed quest IDs
        done_ids = set()
        for q in (ws.get("quests", {}).get("done") or []):
            qid = q.get("id")
            if qid:
                done_ids.add(str(qid))
        # Find NPCs with available quests
        quest_npcs = []
        for e in nearby:
            if not (e.get("kind") == "npc" or e.get("type") == "npc"):
                continue
            qids = e.get("questIds") or ([e.get("questId")] if e.get("questId") else [])
            if not qids:
                continue
            available = [qid for qid in qids if qid and str(qid) not in done_ids]
            if available:
                e["_available_quests"] = available
                quest_npcs.append(e)
        if quest_npcs:
            quest_npcs.sort(key=lambda n: n.get("dist", float("inf")))
            fsm.quest_giver = quest_npcs[0]
            fsm.state = QuestState.FIND_GIVER
            return self._handle_find_giver(fsm, ws, info)
        return ACTION_EXPLORE, {"reason": "no_available_quest_giver"}

    def _handle_find_giver(self, fsm, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Navigate to quest giver."""
        if not fsm.quest_giver:
            nearby = info.get("nearby", []) or []
            quest_npcs = [
                e for e in nearby
                if (e.get("kind") == "npc" or e.get("type") == "npc")
                and (e.get("questIds") or e.get("questId"))
            ]
            if quest_npcs:
                quest_npcs.sort(key=lambda n: n.get("dist", float("inf")))
                fsm.quest_giver = quest_npcs[0]
            else:
                return ACTION_EXPLORE, {"reason": "no_giver_nearby"}
        if not fsm.quest_giver:
            fsm.state = QuestState.QUEST_NONE
            return ACTION_EXPLORE, {"reason": "no_giver"}
        dist = fsm.quest_giver.get("dist", float("inf"))
        if dist is None:
            dist = self._calc_dist_to_giver(fsm, info)
        if dist <= INTERACT_RANGE:
            fsm.state = QuestState.ACCEPT
            return ACTION_ACCEPT_QUEST, {"npc": fsm.quest_giver}
        return ACTION_NAVIGATE, {"target": fsm.quest_giver, "reason": "approaching_giver"}

    def _handle_accept(self, fsm, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Accept the quest."""
        if fsm.quest_giver:
            fsm.state = QuestState.VERIFY_ACCEPT
            return ACTION_ACCEPT_QUEST, {"npc": fsm.quest_giver}
        fsm.state = QuestState.QUEST_NONE
        return ACTION_EXPLORE, {"reason": "no_giver"}

    def _handle_verify_accept(self, fsm, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Verify quest was accepted."""
        quest_status = ws.get("quest_status", "NONE")
        if quest_status == "ACTIVE":
            fsm.state = QuestState.DO_OBJECTIVE
            return self._handle_do_objective(fsm, ws, info)
        fsm.state = QuestState.ACCEPT
        return ACTION_ACCEPT_QUEST, {"npc": fsm.quest_giver}

    def _handle_do_objective(self, fsm, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Execute quest objective (farm, loot, gather)."""
        quest_status = ws.get("quest_status", "NONE")
        if quest_status == "READY_TO_TURN_IN":
            fsm.state = QuestState.RETURN_TO_GIVER
            return self._handle_return_to_giver(fsm, ws, info)
        if quest_status != "ACTIVE":
            fsm.state = QuestState.ERROR
            return ACTION_EXPLORE, {"reason": "quest_not_active"}
        has_mob = ws.get("has_mob", False)
        objectives = ws.get("quest_struct", {}).get("objectives") or []
        quest_ready = ws.get("quest_system_ready", True)
        if has_mob and quest_ready and len(objectives) > 0:
            return ACTION_FARM, {"reason": "objective_mob"}
        if not quest_ready:
            return ACTION_EXPLORE, {"reason": "quest_system_broken"}
        return ACTION_EXPLORE, {"reason": "no_objective_target"}

    def _handle_verify_progress(self, fsm, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Check quest progress."""
        quest_status = ws.get("quest_status", "NONE")
        if quest_status == "READY_TO_TURN_IN":
            fsm.state = QuestState.RETURN_TO_GIVER
            return self._handle_return_to_giver(fsm, ws, info)
        if quest_status == "ACTIVE":
            fsm.state = QuestState.DO_OBJECTIVE
            return self._handle_do_objective(fsm, ws, info)
        fsm.state = QuestState.ERROR
        return ACTION_EXPLORE, {"reason": "quest_state_unknown"}

    def _handle_return_to_giver(self, fsm, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Return to quest giver for turn-in."""
        if not fsm.quest_giver:
            # Try to restore giver from nearby NPCs
            for e in ((info or {}).get("nearby") or []):
                ids = e.get("questIds") or []
                qid = fsm.active_quest.get("id") if fsm.active_quest else None
                if (qid and qid in ids) or (not qid and ids):
                    fsm.quest_giver = {"x": e.get("x"), "z": e.get("z"), "id": e.get("id")}
                    break
        if not fsm.quest_giver:
            fsm.state = QuestState.QUEST_NONE
            return ACTION_EXPLORE, {"reason": "no_giver"}
        dist = self._calc_dist_to_giver(fsm, info)
        if dist is not None and dist <= INTERACT_RANGE:
            fsm.state = QuestState.TURN_IN
            return ACTION_TURN_IN_QUEST, {"npc": fsm.quest_giver}
        return ACTION_NAVIGATE, {"target": fsm.quest_giver, "reason": "returning_to_giver"}

    def _handle_turn_in(self, fsm, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Turn in the quest."""
        if fsm.quest_giver:
            fsm.state = QuestState.VERIFY_TURN_IN
            return ACTION_TURN_IN_QUEST, {"npc": fsm.quest_giver}
        fsm.state = QuestState.QUEST_NONE
        return ACTION_EXPLORE, {"reason": "no_giver"}

    def _handle_verify_turn_in(self, fsm, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Verify quest turn-in."""
        quest_status = ws.get("quest_status", "NONE")
        if quest_status == "DONE":
            fsm.state = QuestState.DONE
            return ACTION_EXPLORE, {"reason": "quest_complete"}
        if quest_status == "READY_TO_TURN_IN":
            fsm.state = QuestState.TURN_IN
            return ACTION_TURN_IN_QUEST, {"npc": fsm.quest_giver}
        fsm.state = QuestState.RETURN_TO_GIVER
        return ACTION_EXPLORE, {"reason": "turn_in_failed"}

    def _handle_respawn(self, fsm, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Handle respawn state."""
        player = info.get("player", {}) or {}
        dead = player.get("dead", False)
        hp = player.get("hp", 0)
        if not dead and hp > 0:
            fsm.state = QuestState.QUEST_NONE
            return ACTION_EXPLORE, {"reason": "respawn_recovered"}
        return ACTION_HEAL, {"reason": "awaiting_respawn"}

    def _handle_done(self, fsm, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Quest done — reset and search for next."""
        fsm.reset()
        return ACTION_EXPLORE, {"reason": "quest_done_search_next"}

    def _handle_error(self, fsm, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Error state — try to recover."""
        if fsm.active_quest:
            fsm.state = QuestState.DO_OBJECTIVE
            return self._handle_do_objective(fsm, ws, info)
        else:
            fsm.state = QuestState.QUEST_NONE
            return ACTION_EXPLORE, {"reason": "error_no_quest"}

    def decide_with_signals(self, fsm, world_state: dict, info: dict,
                            signals: dict, allowed_skills: tuple) -> Tuple[str, Dict]:
        """Decide action when AutonomyLoop emits signals (recovery/loop/anchor).

        ArbitrationLayer decides WHAT to do; AutonomyLoop only detects conditions.
        This method handles signal-based decisions, then falls back to state-based.

        Args:
            fsm: GoalFSM instance (read-only).
            world_state: Current world state.
            info: Additional info (nearby, player).
            signals: Dict from AutonomyLoop (recovery_needed, loop_detected, anchor_needed).
            allowed_skills: Masked skills from AutonomyLoop.

        Returns:
            (action_name, ctx) — the action for the Skill Layer to execute.
        """
        if not signals:
            return self.decide(fsm, world_state, info)

        # Priority 1: anchor — agent too far from giver during active quest
        if "anchor_needed" in signals:
            giver = fsm.quest_giver
            if giver:
                fsm.state = QuestState.RETURN_TO_GIVER
                return ACTION_NAVIGATE, {"target": giver, "reason": "anchor_return_to_giver"}
            # No giver known — explore to find one
            return ACTION_EXPLORE, {"reason": "anchor_no_giver"}

        # Priority 2: recovery needed — skill precondition failed, recovery planned
        if "recovery_needed" in signals:
            rec = signals["recovery_needed"]
            skill = rec.get("skill")
            if skill and skill in allowed_skills:
                return skill, {"reason": "recovery_action", "recovery": rec}
            # Recovery skill not in allowed skills — fall through to state-based
            return self.decide(fsm, world_state, info)

        # Priority 3: loop detected — repeated action without progress
        if "loop_detected" in signals:
            trip = signals["loop_detected"]
            recovery_action = trip.get("recovery_action", "replan")
            # Map recovery action to a skill the agent can execute
            from autonomy import RECOVERY_TO_SKILL
            skill = RECOVERY_TO_SKILL.get(recovery_action)
            if skill and skill in allowed_skills:
                return skill, {"reason": "loop_recovery", "trip": trip}
            # If recovery skill not available, try alternate actions
            for alt_skill in allowed_skills:
                if alt_skill not in ("farm", trip.get("action")):
                    return alt_skill, {"reason": "loop_alternate", "trip": trip}
            # All else fails — replan via explore
            return ACTION_EXPLORE, {"reason": "loop_replan", "trip": trip}

        # Priority 4: subgoal navigation — Planner wants to move
        if "subgoal_nav" in signals:
            return ACTION_EXPLORE, {"reason": "subgoal_navigation", "signals": signals}

        # Fallback to state-based decision
        return self.decide(fsm, world_state, info)

    def _calc_dist_to_giver(self, fsm, info: dict) -> Optional[float]:
        """Calculate distance to quest giver."""
        if not fsm.quest_giver:
            return None
        gx, gz = fsm.quest_giver.get("x"), fsm.quest_giver.get("z")
        if gx is None or gz is None:
            return None
        ppos = info.get("player_pos") or [0, 0]
        return ((gx - ppos[0]) ** 2 + (gz - ppos[1]) ** 2) ** 0.5
