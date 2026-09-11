"""Action masking for the high-level agent skill space.

The canonical step ordering lives in hierarchical_env.SKILLS and mirrors
src/bridge/actions.cjs. Endpoint-only skills use BRIDGE_ENDPOINT_SKILLS.
"""
from typing import Any, Dict, List

from skill_contracts import check_preconditions
from hierarchical_env import SKILLS as SKILL_INDEX

# O(1) lookup instead of rebuilding/searching the SKILLS list on every action.
_SKILL_TO_INDEX = {name: i for i, name in enumerate(SKILL_INDEX)}

# Skills executed by dedicated bridge endpoints rather than step idx.
BRIDGE_ENDPOINT_SKILLS = {
    "respawn": "respawn",
    "explore": "navigate",
    "navigate": "navigate",
    "flee": "navigate",
}

# Navigation is always possible as a fallback. flee is included as an explicit
# survival alternative so a blocked combat action cannot collapse to exploration.
ALWAYS_AVAILABLE = ("explore", "navigate", "flee")
EXTRA_SKILLS = ("respawn", "navigate", "flee")


def maskable_skills() -> List[str]:
    """All skills for which a mask can be computed."""
    return list(SKILL_INDEX) + [s for s in EXTRA_SKILLS if s not in _SKILL_TO_INDEX]


def get_action_mask(obs: Dict[str, Any]) -> List[int]:
    """Return the step-space mask, in canonical bridge order."""
    return [1 if check_preconditions(s, obs)["ok"] else 0 for s in SKILL_INDEX]


def available_actions(obs: Dict[str, Any]) -> List[str]:
    """Return currently usable skills plus navigation/survival fallbacks."""
    out = [s for s in SKILL_INDEX if check_preconditions(s, obs)["ok"]]
    return out or list(ALWAYS_AVAILABLE)


def mask_candidates(cands: List[str], obs: Dict[str, Any]) -> List[str]:
    """Filter policy candidates while retaining navigation and flee options."""
    ok = list(ALWAYS_AVAILABLE)
    for c in cands:
        if c not in ALWAYS_AVAILABLE and check_preconditions(c, obs)["ok"]:
            ok.append(c)
    return ok


def why_blocked(skill: str, obs: Dict[str, Any]) -> List[str]:
    """Return failed preconditions for diagnostics/recovery."""
    return check_preconditions(skill, obs)["failed"]


def index_of(skill: str) -> int:
    """Return the canonical step index, or -1 for endpoint-only skills."""
    return _SKILL_TO_INDEX.get(skill, -1)


def endpoint_of(skill: str):
    """Return the bridge endpoint for an endpoint-only skill, if any."""
    return BRIDGE_ENDPOINT_SKILLS.get(skill)
