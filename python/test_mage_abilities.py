"""TDD tests for mage ability awareness (user 2026-08-22):

The character is a MAGE (official src/sim/content/classes.ts:133): mana
resource, ranged wand (30yd), base kit at level<=5 includes fireball,
frostbolt (slow!), frost_armor, arcane_intellect, blink, ice_block.
The agent currently knows NOTHING about this: no mana in the observation,
no abilities list, no way to cast. It melee-tanks mobs like a warrior.

Contract from the official game source:
  - p.resource / p.maxResource / p.resourceType ('mana' for mage)
  - sim.known[i] -> ResolvedAbility {def: {id, name, cost, castTime,
    cooldown, range, school}, rank}
  - castAbility(ctx, abilityId) / sim.castAbilityBySlot(slot); auto-acquires
    nearest attacking mob when untargeted (casting_lifecycle.ts:771)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from world_state import build_world_state
import policy
from policy import GoalManager
from memory import ExperienceStore


def _mage_info(hp=100, max_hp=100, mana=80, max_mana=100):
    return {
        "player": {"hp": hp, "maxHp": max_hp, "dead": False},
        "mana": mana, "maxMana": max_mana,
        "abilities": [
            {"id": "fireball", "name": "Cinderbolt", "cost": 30, "castTime": 1.5,
             "cooldown": 0, "range": 30, "ready": True},
            {"id": "frostbolt", "name": "Rimelance", "cost": 25, "castTime": 1.5,
             "cooldown": 0, "range": 30, "ready": True},
            {"id": "blink", "name": "Blink", "cost": 45, "castTime": 0,
             "cooldown": 15, "range": 0, "ready": False},  # on cooldown
        ],
        "player_pos": [0, 0],
        "nearby": [
            {"id": 7, "kind": "mob", "type": "mob", "name": "wolf", "x": 8, "z": 6,
             "maxHp": 40, "hp": 40, "hostile": True, "dead": False},
        ],
        "inventory": [],
        "quests": {"active": [], "ready": [], "done": []},
        "kills": 0, "deaths": 0,
    }


# ---------- observation: mana + abilities must reach WorldState ----------

def test_world_state_exposes_mana():
    ws = build_world_state(_mage_info())
    assert abs(ws["mana_frac"] - 0.8) < 1e-6, ws.get("mana_frac")


def test_world_state_defaults_without_mana_fields():
    """Non-mage or older bridge without mana fields -> neutral value, no crash."""
    info = _mage_info()
    del info["mana"], info["maxMana"], info["abilities"]
    ws = build_world_state(info)
    assert ws["mana_frac"] == -1.0  # sentinel: unknown/not applicable


def test_world_state_lists_castable_abilities():
    ws = build_world_state(_mage_info())
    ab = ws.get("abilities")
    assert isinstance(ab, list) and len(ab) == 3
    ids = {a["id"] for a in ab}
    assert "fireball" in ids and "frostbolt" in ids
    fb = next(a for a in ab if a["id"] == "fireball")
    assert fb["ready"] is True and fb["cost"] == 30
    bl = next(a for a in ab if a["id"] == "blink")
    assert bl["ready"] is False  # on cooldown


def test_world_state_flags_ready_damage_spell():
    ws = build_world_state(_mage_info())
    assert ws["has_ready_damage_spell"] is True
    # all spells too expensive for current mana -> not ready to cast
    ws2 = build_world_state(_mage_info(mana=10))
    assert ws2["has_ready_damage_spell"] is False


# ---------- policy: mage nuking skills ----------

def _gm():
    return GoalManager(ExperienceStore())


def test_cast_frostbolt_candidate_when_mob_near_and_mana_ok():
    gm = _gm()
    ws = build_world_state(_mage_info())
    cands = gm._candidates(_mage_info(), ws, goal="DO_OBJECTIVE")
    assert "cast_frostbolt" in cands, cands
    assert "cast_fireball" in cands, cands


def test_no_cast_candidates_when_oom():
    gm = _gm()
    info = _mage_info(mana=5, max_mana=100)
    ws = build_world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "cast_frostbolt" not in cands, cands
    assert "cast_fireball" not in cands, cands


def test_no_cast_when_all_on_cooldown():
    gm = _gm()
    info = _mage_info()
    for a in info["abilities"]:
        a["ready"] = False
    ws = build_world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "cast_frostbolt" not in cands and "cast_fireball" not in cands


def test_phase_gate_keeps_cast_skills_in_do_objective():
    assert "cast_frostbolt" in policy.PHASE_ALLOWED["DO_OBJECTIVE"]
    assert "cast_fireball" in policy.PHASE_ALLOWED["DO_OBJECTIVE"]


# ---------- skill execution contract (browser_env sends the right command) ----------

def test_skill_index_includes_cast_skills():
    from hierarchical_env import SKILLS
    assert "cast_frostbolt" in SKILLS
    assert "cast_fireball" in SKILLS
