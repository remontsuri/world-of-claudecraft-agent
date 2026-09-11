"""Quest lifecycle coordinator.

Keeps orchestration thin: the policy selects the ``quest_chain`` skill,
capabilities perform mutations, and this class advances the quest lifecycle
from observable state.  It owns no persistent quest state; ``agent.done_ids``
is the single source of truth.
"""
from typing import Optional, Set

from quest_chaining import find_next_quest
from quest_objective import Objective, dispatch_objective, resolve_objective, resolve_target
from quest_capability import QuestCapability


class ChainResult:
    """Result of one quest-chain tick."""

    __slots__ = ("verdict", "action", "quest_id", "objective", "target")

    def __init__(
        self,
        verdict: str,
        action: str = "",
        quest_id: str = "",
        objective: Optional[Objective] = None,
        target: Optional[dict] = None,
    ):
        self.verdict = verdict
        self.action = action
        self.quest_id = quest_id
        self.objective = objective
        self.target = target

    def __repr__(self) -> str:
        return f"ChainResult(verdict={self.verdict}, action={self.action}, quest_id={self.quest_id})"


class QuestChain:
    """Advance one step of the quest lifecycle from current world state.

    ``QuestChain`` is deliberately stateless apart from references to the
    agent/environment. Quest completion belongs to ``agent.done_ids`` so there
    cannot be a second in-memory completion set that diverges after restart.
    """

    def __init__(self, agent, env):
        self.agent = agent
        self.env = env
        self.cap = QuestCapability(env)

    @property
    def done_ids(self) -> Set[str]:
        """Canonical completed-quest set owned by Agent."""
        ids = getattr(self.agent, "done_ids", None)
        if ids is None:
            # Keep compatibility with lightweight test doubles without creating
            # a second production state owner.
            ids = set()
            self.agent.done_ids = ids
        return ids

    def discover(self) -> Optional[dict]:
        """Find the best available quest giver not present in ``agent.done_ids``."""
        return find_next_quest(self.env._last_info or {}, self.done_ids)

    def accept_and_verify(self, giver: dict, quest_id: str) -> bool:
        """Navigate, accept, then verify the quest is ACTIVE."""
        gx, gz = giver.get("x"), giver.get("z")
        if gx is not None and gz is not None:
            self.env._navigate_to_coord(gx, gz, max_steps=80)

        if self.cap.accept(quest_id) != "SUCCESS":
            return False

        active = ((self.env._last_info or {}).get("quests") or {}).get("active") or []
        return any(str(q.get("id")) == str(quest_id) for q in active)

    def resolve_objective(self, quest: dict) -> Optional[Objective]:
        return resolve_objective(quest, self.env._last_info or {})

    def resolve_target(self, objective: Objective) -> Optional[dict]:
        return resolve_target(objective, self.env._last_info or {})

    def execute_objective(self, objective: Objective, target: dict, ctx: Optional[dict] = None) -> str:
        return dispatch_objective(objective, target, self.env, ctx or {})

    def verify_progress(self, quest: dict) -> bool:
        return self.cap.quest_status(quest) == "READY_TO_TURN_IN"

    def turn_in_and_verify(self, quest: dict) -> bool:
        """Navigate, turn in, and rely on QuestCapability's authoritative verification."""
        result = self.cap.navigate_to_turn_in(quest)
        if result == "FAILURE":
            return False
        return self.cap.turn_in(quest) == "SUCCESS"

    def find_next_quest(self) -> Optional[dict]:
        return find_next_quest(self.env._last_info or {}, self.done_ids)

    def run_chain(self) -> ChainResult:
        """Advance the quest state machine by one bounded, observable transition."""
        info = self.env._last_info or {}
        quests = info.get("quests") or {}
        all_q = (quests.get("active") or []) + (quests.get("ready") or [])

        if not all_q:
            discovery = self.discover()
            if discovery is None:
                return ChainResult("FAILURE", action="discover")
            quest_id = str(discovery.get("quest_id") or "")
            if not quest_id:
                return ChainResult("FAILURE", action="discover")
            if self.accept_and_verify(discovery["npc"], quest_id):
                return ChainResult("SUCCESS", action="accept_quest", quest_id=quest_id)
            return ChainResult("FAILURE", action="accept_quest", quest_id=quest_id)

        # Prefer a ready quest over an arbitrary active quest when both exist.
        quest = next((q for q in all_q if q.get("state") == "ready"), all_q[0])
        quest_id = str(quest.get("id") or "")

        if self.verify_progress(quest):
            if self.turn_in_and_verify(quest):
                self.done_ids.add(quest_id)
                return ChainResult("SUCCESS", action="turn_in_quest", quest_id=quest_id)
            return ChainResult("PARTIAL", action="turn_in_quest", quest_id=quest_id)

        objective = self.resolve_objective(quest)
        if objective is None:
            return ChainResult("PARTIAL", action="resolve_objective", quest_id=quest_id)

        target = self.resolve_target(objective)
        if target is None:
            return ChainResult("PARTIAL", action="resolve_target", quest_id=quest_id)

        verdict = self.execute_objective(objective, target)
        return ChainResult(
            verdict,
            action="execute_objective",
            quest_id=quest_id,
            objective=objective,
            target=target,
        )
