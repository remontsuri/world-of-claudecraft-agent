"""safety_layer.py — Safety layer for critical HP override.

This module provides a safety net that forces healing when HP falls below
a critical threshold. It is SEPARATE from the learning policy and the
ArbitrationLayer — it exists solely to prevent the agent from dying due
to a bad learning decision.

Contract:
    - check(world_state) -> Optional[str]
    - Returns "heal" if HP < 0.2, else None
    - Does NOT learn, does NOT modify policy, does NOT track state
"""

from typing import Optional

# Critical HP threshold — below this, the agent MUST heal regardless of
# what the policy or FSM suggests. This is a safety override, not a
# learning rule.
CRITICAL_HP_FRAC = 0.2


def check(world_state: dict) -> Optional[str]:
    """Return 'heal' if HP is below critical threshold, else None.

    This is the ONLY hard-coded safety rule in the agent. Everything else
    (quest selection, combat, exploration) is learned or arbitrated.

    Args:
        world_state: Current world state dict with 'hp_frac' key.

    Returns:
        'heal' if hp_frac < CRITICAL_HP_FRAC, else None.
    """
    hp_frac = world_state.get("hp_frac", 1.0)
    if hp_frac < CRITICAL_HP_FRAC:
        return "heal"
    return None


def should_force_heal(world_state: dict) -> bool:
    """Convenience predicate: True if HP is critical."""
    return check(world_state) == "heal"
