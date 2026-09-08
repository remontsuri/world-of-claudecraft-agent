"""hierarchical_env.py — minimal stub for backward compatibility.

The original HierarchicalWoWEnv was removed in commit 36a66fd (unused RL env).
This stub exports the constants and SKILLS list that other modules import.
The live agent uses BrowserEnv from browser_env.py, not this module.
"""
# Skill indices MUST match browser_env.py / bridge order:
# 0 farm, 1 loot, 2 accept_quest, 3 turn_in_quest, 4 sell_junk,
# 5 gather, 6 craft, 7 heal, 8 equip, 9 buy
SKILLS = [
    "farm", "loot", "accept_quest", "turn_in_quest", "sell_junk",
    "gather", "craft", "heal", "equip", "buy",
    "cast_frostbolt", "cast_fireball", "craft_item",
]
N_SKILLS = len(SKILLS)

# Low-level action indices from src/sim/obs.ts ACTIONS
ACT_FORWARD = 1
ACT_TURN_LEFT = 3
ACT_TURN_RIGHT = 4
ACT_STRAFE_RIGHT = 6
ACT_TARGET_NEAREST = 8
ACT_ATTACK = 9
ACT_FARM = 0
ACT_INTERACT = 58
ACT_EAT_DRINK = 7


class HierarchicalWoWEnv:
    """Stub — not used in production. Agent uses BrowserEnv instead."""

    def __init__(self, player_class="warrior", max_steps=2000, seed=0):
        raise NotImplementedError(
            "HierarchicalWoWEnv is deprecated. Use BrowserEnv from browser_env.py"
        )
