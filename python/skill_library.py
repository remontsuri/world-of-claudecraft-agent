"""skill_library.py — persistent skill library for WoC agent.

Each skill has:
- skill_id, name, description, version, category
- preconditions, postconditions, implementation
- dependencies, composition
- success_count, failure_count, last_success, last_failure
- average_duration, known_failure_modes, environment_requirements
"""

import json
import os
import time
from typing import Any, Dict, List, Optional


class Skill:
    def __init__(self, skill_id: str, name: str, description: str = "",
                 category: str = "primitive", implementation: str = "",
                 preconditions: dict = None, postconditions: dict = None,
                 dependencies: list = None):
        self.skill_id = skill_id
        self.name = name
        self.description = description
        self.version = "1.0.0"
        self.category = category
        self.implementation = implementation
        self.preconditions = preconditions or {}
        self.postconditions = postconditions or {}
        self.dependencies = dependencies or []
        self.composition = []
        self.success_count = 0
        self.failure_count = 0
        self.last_success = None
        self.last_failure = None
        self.average_duration = 0.0
        self.known_failure_modes = []
        self.environment_requirements = {}
        self.created_at = time.time()
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    @classmethod
    def from_dict(cls, data: dict) -> "Skill":
        skill = cls(
            skill_id=data.get("skill_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            category=data.get("category", "primitive"),
            implementation=data.get("implementation", ""),
            preconditions=data.get("preconditions"),
            postconditions=data.get("postconditions"),
            dependencies=data.get("dependencies"),
        )
        for k, v in data.items():
            if hasattr(skill, k) and k not in ("skill_id", "name"):
                setattr(skill, k, v)
        return skill

    def record_success(self, duration: float = 0.0):
        self.success_count += 1
        self.last_success = time.time()
        self.average_duration = (self.average_duration * (self.success_count - 1) + duration) / self.success_count
        self.updated_at = time.time()

    def record_failure(self, error: str = "", duration: float = 0.0):
        self.failure_count += 1
        self.last_failure = time.time()
        if error and error not in self.known_failure_modes:
            self.known_failure_modes.append(error)
        self.updated_at = time.time()

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    @property
    def is_stable(self) -> bool:
        return self.success_count >= 3 and self.success_rate >= 0.7

    @property
    def is_production_ready(self) -> bool:
        return self.success_count >= 5 and self.success_rate >= 0.8


class SkillLibrary:
    def __init__(self, path: str = None):
        self.path = path or os.path.join(
            os.path.dirname(__file__), "skill_library.json"
        )
        self.skills: Dict[str, Skill] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                for skill_data in data.get("skills", []):
                    skill = Skill.from_dict(skill_data)
                    self.skills[skill.skill_id] = skill
            except Exception as e:
                print(f"[skill_library] load error: {e}", flush=True)

    def save(self):
        data = {
            "version": "1.0.0",
            "updated_at": time.time(),
            "skills": [s.to_dict() for s in self.skills.values()],
        }
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def add(self, skill: Skill) -> bool:
        if skill.skill_id in self.skills:
            return False
        self.skills[skill.skill_id] = skill
        self.save()
        return True

    def get(self, skill_id: str) -> Optional[Skill]:
        return self.skills.get(skill_id)

    def search(self, query: str = None, category: str = None, 
               min_success_rate: float = 0.0) -> List[Skill]:
        results = []
        for skill in self.skills.values():
            if category and skill.category != category:
                continue
            if min_success_rate and skill.success_rate < min_success_rate:
                continue
            if query and query.lower() not in (skill.name + skill.description).lower():
                continue
            results.append(skill)
        return sorted(results, key=lambda s: s.success_rate, reverse=True)

    def find_similar(self, goal: str, threshold: float = 0.3) -> List[Skill]:
        """Find skills similar to the goal using simple keyword matching."""
        goal_words = set(goal.lower().split())
        results = []
        for skill in self.skills.values():
            skill_words = set((skill.name + " " + skill.description).lower().split())
            if not skill_words:
                continue
            overlap = len(goal_words & skill_words) / max(len(goal_words), 1)
            if overlap >= threshold:
                results.append((overlap, skill))
        results.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in results]

    def get_stats(self) -> dict:
        total = len(self.skills)
        production = sum(1 for s in self.skills.values() if s.is_production_ready)
        stable = sum(1 for s in self.skills.values() if s.is_stable)
        experimental = total - stable
        return {
            "total": total,
            "production_ready": production,
            "stable": stable,
            "experimental": experimental,
        }


# Primitive skills — base library
def create_primitive_skills() -> List[Skill]:
    """Create the base set of primitive skills."""
    return [
        Skill("navigate", "navigate", "Navigate to a target position", "movement",
              preconditions={"has_target": True},
              postconditions={"at_target": True}),
        Skill("explore", "explore", "Explore the nearby area", "movement",
              postconditions={"area_explored": True}),
        Skill("target", "target", "Acquire a target mob", "combat",
              preconditions={"mob_nearby": True},
              postconditions={"has_target": True}),
        Skill("attack", "attack", "Attack the current target", "combat",
              preconditions={"has_target": True, "in_range": True},
              postconditions={"target_damaged": True}),
        Skill("face", "face", "Face the target", "combat",
              preconditions={"has_target": True},
              postconditions={"facing_target": True}),
        Skill("loot", "loot", "Loot a corpse", "interaction",
              preconditions={"corpse_nearby": True},
              postconditions={"looted": True}),
        Skill("gather", "gather", "Gather a resource node", "interaction",
              preconditions={"node_nearby": True},
              postconditions={"resource_collected": True}),
        Skill("interact", "interact", "Interact with an NPC", "interaction",
              preconditions={"npc_nearby": True},
              postconditions={"interacted": True}),
        Skill("heal", "heal", "Heal the player", "survival",
              preconditions={"has_healing": True, "hp_below_max": True},
              postconditions={"hp_increased": True}),
        Skill("flee", "flee", "Flee from combat", "survival",
              preconditions={"in_combat": True, "hp_low": True},
              postconditions={"out_of_combat": True}),
        Skill("respawn", "respawn", "Respawn after death", "survival",
              preconditions={"is_dead": True},
              postconditions={"is_alive": True}),
        Skill("accept_quest", "accept_quest", "Accept a quest from NPC", "quest",
              preconditions={"quest_available": True, "npc_nearby": True},
              postconditions={"quest_active": True}),
        Skill("turn_in_quest", "turn_in_quest", "Turn in a completed quest", "quest",
              preconditions={"quest_ready": True, "at_giver": True},
              postconditions={"quest_done": True}),
        Skill("return_to_giver", "return_to_giver", "Return to quest giver", "quest",
              preconditions={"has_quest": True},
              postconditions={"at_giver": True}),
        Skill("buy", "buy", "Buy an item from vendor", "economy",
              preconditions={"vendor_nearby": True, "has_money": True},
              postconditions={"item_acquired": True}),
        Skill("sell_junk", "sell_junk", "Sell junk items", "economy",
              preconditions={"vendor_nearby": True, "has_junk": True},
              postconditions={"junk_sold": True}),
        Skill("craft", "craft", "Craft an item", "profession",
              preconditions={"has_reagents": True, "has_tool": True},
              postconditions={"item_crafted": True}),
        Skill("equip", "equip", "Equip an item", "equipment",
              preconditions={"has_item": True},
              postconditions={"item_equipped": True}),
    ]


def ensure_library_initialized(path: str = None) -> SkillLibrary:
    """Ensure the skill library exists with primitive skills."""
    lib = SkillLibrary(path)
    if not lib.skills:
        for skill in create_primitive_skills():
            lib.add(skill)
        lib.save()
    return lib
