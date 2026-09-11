"""curriculum.py — automatic curriculum for WoC agent.

Manages skill progression:
LEVEL 0: basic movement
LEVEL 1: navigation
LEVEL 2: NPC interaction
LEVEL 3: quest acceptance
LEVEL 4: basic combat
LEVEL 5: combat + loot
LEVEL 6: quest completion
LEVEL 7: healing/recovery
LEVEL 8: economy
LEVEL 9: gathering
LEVEL 10: crafting
LEVEL 11: compound quests
LEVEL 12: adaptive combat
LEVEL 13: multi-skill planning
LEVEL 14: self-recovery
LEVEL 15: open-ended autonomous play
"""

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple


# Difficulty levels with their required skills and goals
CURRICULUM_LEVELS = {
    0: {
        "name": "basic_movement",
        "description": "Learn to move and explore",
        "goals": ["explore", "navigate"],
        "required_skills": ["explore"],
        "success_criteria": {"explore_success_rate": 0.5},
    },
    1: {
        "name": "navigation",
        "description": "Navigate to specific locations",
        "goals": ["navigate_to_npc", "navigate_to_position"],
        "required_skills": ["navigate"],
        "success_criteria": {"navigate_success_rate": 0.6},
    },
    2: {
        "name": "npc_interaction",
        "description": "Interact with NPCs",
        "goals": ["find_npc", "interact_with_npc"],
        "required_skills": ["navigate", "interact"],
        "success_criteria": {"interact_success_rate": 0.7},
    },
    3: {
        "name": "quest_acceptance",
        "description": "Accept quests from NPCs",
        "goals": ["accept_quest"],
        "required_skills": ["navigate", "interact", "accept_quest"],
        "success_criteria": {"accept_quest_success_rate": 0.7},
    },
    4: {
        "name": "basic_combat",
        "description": "Fight weak mobs",
        "goals": ["kill_weak_mob"],
        "required_skills": ["navigate", "target", "attack", "face"],
        "success_criteria": {"combat_success_rate": 0.5},
    },
    5: {
        "name": "combat_and_loot",
        "description": "Kill mobs and loot corpses",
        "goals": ["kill_mob", "loot_corpse"],
        "required_skills": ["navigate", "target", "attack", "loot"],
        "success_criteria": {"loot_success_rate": 0.6},
    },
    6: {
        "name": "quest_completion",
        "description": "Complete a full quest cycle",
        "goals": ["complete_quest"],
        "required_skills": ["accept_quest", "navigate", "target", "attack", "loot", "return_to_giver", "turn_in_quest"],
        "success_criteria": {"quest_completion_rate": 0.5},
    },
    7: {
        "name": "healing_recovery",
        "description": "Heal and recover after combat",
        "goals": ["heal_after_combat", "recover_from_death"],
        "required_skills": ["heal", "respawn"],
        "success_criteria": {"heal_success_rate": 0.7},
    },
    8: {
        "name": "economy",
        "description": "Buy and sell items",
        "goals": ["buy_item", "sell_junk"],
        "required_skills": ["navigate", "interact", "buy", "sell_junk"],
        "success_criteria": {"trade_success_rate": 0.6},
    },
    9: {
        "name": "gathering",
        "description": "Gather resource nodes",
        "goals": ["gather_resource"],
        "required_skills": ["navigate", "gather"],
        "success_criteria": {"gather_success_rate": 0.6},
    },
    10: {
        "name": "crafting",
        "description": "Craft items from gathered resources",
        "goals": ["craft_item"],
        "required_skills": ["gather", "craft"],
        "success_criteria": {"craft_success_rate": 0.5},
    },
    11: {
        "name": "compound_quests",
        "description": "Complete multi-step quests",
        "goals": ["complete_hunting_quest", "complete_gathering_quest"],
        "required_skills": ["accept_quest", "navigate", "target", "attack", "loot", "return_to_giver", "turn_in_quest"],
        "success_criteria": {"compound_quest_rate": 0.4},
    },
    12: {
        "name": "adaptive_combat",
        "description": "Fight stronger enemies and adapt",
        "goals": ["kill_strong_mob", "flee_when_weak"],
        "required_skills": ["target", "attack", "face", "flee", "heal"],
        "success_criteria": {"adaptive_combat_rate": 0.4},
    },
    13: {
        "name": "multi_skill_planning",
        "description": "Plan and execute multi-skill sequences",
        "goals": ["plan_quest_chain", "execute_plan"],
        "required_skills": ["navigate", "interact", "accept_quest", "target", "attack", "loot", "return_to_giver", "turn_in_quest"],
        "success_criteria": {"plan_success_rate": 0.4},
    },
    14: {
        "name": "self_recovery",
        "description": "Recover from failures autonomously",
        "goals": ["recover_from_failure", "adapt_to_state"],
        "required_skills": ["respawn", "heal", "flee", "navigate"],
        "success_criteria": {"recovery_rate": 0.5},
    },
    15: {
        "name": "autonomous_play",
        "description": "Open-ended autonomous gameplay",
        "goals": ["autonomous_quest_loop", "skill_discovery"],
        "required_skills": ["explore", "navigate", "interact", "accept_quest", "target", "attack", "loot", "heal", "return_to_giver", "turn_in_quest"],
        "success_criteria": {"autonomous_success_rate": 0.3},
    },
}


class CurriculumState:
    """Tracks curriculum progress."""

    def __init__(self, path: str = None):
        self.path = path or os.path.join(
            os.path.dirname(__file__), "curriculum_state.json"
        )
        self.current_level: int = 0
        self.mastered_skills: List[str] = []
        self.unstable_skills: List[str] = []
        self.failed_skills: List[str] = []
        self.current_goals: List[str] = []
        self.completed_goals: List[str] = []
        self.blocked_goals: List[str] = []
        self.skill_dependencies: Dict[str, List[str]] = {}
        self.level_progress: Dict[int, float] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                for k, v in data.items():
                    if hasattr(self, k):
                        setattr(self, k, v)
            except Exception:
                pass

    def save(self):
        data = {
            "current_level": self.current_level,
            "mastered_skills": self.mastered_skills,
            "unstable_skills": self.unstable_skills,
            "failed_skills": self.failed_skills,
            "current_goals": self.current_goals,
            "completed_goals": self.completed_goals,
            "blocked_goals": self.blocked_goals,
            "skill_dependencies": self.skill_dependencies,
            "level_progress": self.level_progress,
            "updated_at": time.time(),
        }
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def get_next_goal(self) -> Optional[str]:
        """Get the next uncompleted goal at the current level."""
        level_data = CURRICULUM_LEVELS.get(self.current_level, {})
        goals = level_data.get("goals", [])
        for goal in goals:
            if goal not in self.completed_goals:
                return goal
        return None

    def advance_level(self) -> bool:
        """Advance to the next level if current level is complete."""
        level_data = CURRICULUM_LEVELS.get(self.current_level, {})
        goals = level_data.get("goals", [])
        if all(g in self.completed_goals for g in goals):
            self.current_level += 1
            self.save()
            return True
        return False

    def mark_goal_complete(self, goal: str):
        """Mark a goal as completed."""
        if goal not in self.completed_goals:
            self.completed_goals.append(goal)
        if goal in self.current_goals:
            self.current_goals.remove(goal)
        self.save()

    def mark_skill_mastered(self, skill_id: str):
        """Mark a skill as mastered."""
        if skill_id not in self.mastered_skills:
            self.mastered_skills.append(skill_id)
        if skill_id in self.unstable_skills:
            self.unstable_skills.remove(skill_id)
        self.save()

    def mark_skill_unstable(self, skill_id: str):
        """Mark a skill as unstable."""
        if skill_id not in self.unstable_skills:
            self.unstable_skills.append(skill_id)
        self.save()

    def mark_skill_failed(self, skill_id: str):
        """Mark a skill as failed."""
        if skill_id not in self.failed_skills:
            self.failed_skills.append(skill_id)
        self.save()

    def get_status(self) -> dict:
        """Get curriculum status."""
        level_data = CURRICULUM_LEVELS.get(self.current_level, {})
        return {
            "current_level": self.current_level,
            "level_name": level_data.get("name", "unknown"),
            "level_description": level_data.get("description", ""),
            "current_goals": self.current_goals,
            "completed_goals": self.completed_goals,
            "mastered_skills": len(self.mastered_skills),
            "unstable_skills": len(self.unstable_skills),
            "failed_skills": len(self.failed_skills),
        }
