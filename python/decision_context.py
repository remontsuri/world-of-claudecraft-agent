"""decision_context.py — explicit decision context (ARCHITECTURE-CONSENSUS §12).

Replaces the hidden IPC channel through mutable policy.hints.
AutonomyLoop builds ONE DecisionContext per step; Policy reads it.

Single decision pipeline:
    Observation → GoalFSM/Planner → DecisionContext → Policy → Skill
"""
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class DecisionContext:
    """Immutable decision context passed from Autonomy to Policy.

    One per decision cycle. No mutable state leaks between steps.
    """
    allowed_skills: tuple              # from mask_candidates + preconditions
    forced_skill: Optional[str]        # from recovery/loop (PREFERENCE, not force)
    subgoal: Optional[str]             # from Planner
    navigation_intent: Optional[str]   # GO_TO_GIVER, FIND_MOB, EXPLORE, etc.
    target: Optional[dict]             # live entity from NavigationController
    reason: str                        # human-readable why
