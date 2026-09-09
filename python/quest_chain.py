"""quest_chain.py — Full quest lifecycle chain orchestrator.

Orchestrates: discover giver -> accept -> verify ACTIVE -> resolve objective ->
resolve target -> navigate -> execute -> verify progress -> repeat ->
READY_TO_TURN_IN -> navigate back -> turn in -> verify DONE -> next quest.

This module does NOT replace the policy. The policy still chooses skills;
the chain provides goals and verifies transitions.
"""
from typing import Optional, Dict, Set
from quest_objective import resolve_objective, resolve_target, dispatch_objective, Objective
from quest_chaining import find_next_quest


class ChainResult:
    """Result of one chain step."""
    def __init__(self, verdict: str, action: str = "", quest_id: str = "",
                 objective: Objective = None, target: dict = None):
        self.verdict = verdict
        self.action = action
        self.quest_id = quest_id
        self.objective = objective
        self.target = target

    def __repr__(self):
        return f"ChainResult(verdict={self.verdict}, action={self.action}, quest_id={self.quest_id})"


class QuestChain:
    """Orchestrates the full quest lifecycle chain.

    Depends on:
      - env: BrowserEnv (for step(), _last_info, _navigate_to_coord)
      - agent: Agent (for world_mem, policy, fsm, done_ids)
    """

    def __init__(self, agent, env):
        self.agent = agent
        self.env = env
        self.done_ids: Set[str] = set()

    def discover(self) -> Optional[dict]:
        """Find the best quest giver with an available (non-done) quest.

        Returns: {"npc": npc_info, "quest_id": str, "quest_ids": list} or None.
        """
        info = self.env._last_info or {}
        return find_next_quest(info, self.done_ids)

    def accept_and_verify(self, giver: dict, quest_id: str) -> bool:
        """Accept a quest and verify it becomes ACTIVE.

        Returns True if the quest is verified ACTIVE after accept.
        """
        from quest_capability import QuestCapability
        cap = QuestCapability(self.env)
        # Navigate to giver first
        gx = giver.get("x")
        gz = giver.get("z")
        if gx is not None and gz is not None:
            self.env._navigate_to_coord(gx, gz, max_steps=80)
        # Accept
        result = cap.accept(quest_id)
        if result != "SUCCESS":
            return False
        # Verify: check quest is now active
        info_after = self.env._last_info or {}
        active = info_after.get("quests", {}).get("active", [])
        for q in active:
            if str(q.get("id")) == str(quest_id):
                return True
        return False

    def resolve_objective(self, quest: dict) -> Optional[Objective]:
        """Resolve the first incomplete objective of a quest."""
        info = self.env._last_info or {}
        return resolve_objective(quest, info)

    def resolve_target(self, objective: Objective) -> Optional[dict]:
        """Find the target entity for an objective."""
        info = self.env._last_info or {}
        return resolve_target(objective, info)

    def execute_objective(self, objective: Objective, target: dict, ctx: dict) -> str:
        """Execute one step toward the objective. Returns verdict."""
        return dispatch_objective(objective, target, self.env, ctx)

    def verify_progress(self, quest: dict) -> bool:
        """Check if all objectives of a quest are complete.

        Returns True when the quest is READY_TO_TURN_IN.
        """
        from quest_capability import QuestCapability
        cap = QuestCapability(self.env)
        status = cap.quest_status(quest)
        return status == "READY_TO_TURN_IN"

    def turn_in_and_verify(self, quest: dict) -> bool:
        """Turn in a quest and verify DONE.

        Returns True when the quest is verified as DONE.
        """
        from quest_capability import QuestCapability
        cap = QuestCapability(self.env)
        qid = str(quest.get("id"))
        # Navigate to turn-in NPC
        tNpc = quest.get("turnInNpc") or {}
        gx = tNpc.get("x")
        gz = tNpc.get("z")
        if gx is None or gz is None:
            # Fallback: use giver position from nearby
            info = self.env._last_info or {}
            for e in (info.get("nearby") or []):
                ids = e.get("questIds") or []
                if qid in [str(x) for x in ids] and e.get("x") is not None:
                    gx, gz = e.get("x"), e.get("z")
                    break
        if gx is not None and gz is not None:
            self.env._navigate_to_coord(gx, gz, max_steps=80)
        # Turn in
        result = cap.turn_in(quest)
        return result == "SUCCESS"

    def find_next_quest(self) -> Optional[dict]:
        """Find the next quest after a turn-in."""
        info = self.env._last_info or {}
        return find_next_quest(info, self.done_ids)

    def run_chain(self) -> ChainResult:
        """Run one full quest chain iteration.

        This is called by the agent's _run_skill when the policy selects
        'quest_chain' as the action. It performs one step of the chain.
        """
        info = self.env._last_info or {}
        # Check if we have an active quest
        active = info.get("quests", {}).get("active", [])
        ready = info.get("quests", {}).get("ready", [])
        all_q = active + ready

        if not all_q:
            # No active quest — discover and accept
            discovery = self.discover()
            if discovery is None:
                return ChainResult("FAILURE", action="discover")
            npc = discovery["npc"]
            quest_id = discovery["quest_id"]
            if self.accept_and_verify(npc, quest_id):
                return ChainResult("SUCCESS", action="accept_quest", quest_id=quest_id)
            return ChainResult("FAILURE", action="accept_quest")

        # We have an active quest — work on it
        quest = all_q[0]
        quest_id = str(quest.get("id"))

        # Check if ready to turn in
        if self.verify_progress(quest):
            if self.turn_in_and_verify(quest):
                self.done_ids.add(quest_id)
                return ChainResult("SUCCESS", action="turn_in_quest", quest_id=quest_id)
            return ChainResult("PARTIAL", action="turn_in_quest", quest_id=quest_id)

        # Resolve and execute objective
        objective = self.resolve_objective(quest)
        if objective is None:
            # No incomplete objectives — should be ready to turn in
            return ChainResult("PARTIAL", action="resolve_objective", quest_id=quest_id)

        target = self.resolve_target(objective)
        if target is None:
            return ChainResult("PARTIAL", action="resolve_target", quest_id=quest_id)

        verdict = self.execute_objective(objective, target, {})
        return ChainResult(verdict, action="execute_objective", quest_id=quest_id, objective=objective, target=target)
