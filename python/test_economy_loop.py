"""TDD tests for the economy loop (spec: docs/superpowers/specs/2026-08-22-economy-loop-design.md).

Covers the observation + policy layer:
  - inventory with real item ids and counts -> inv_by_id
  - known recipes with reagents -> craftable_now (reagents satisfied)
  - station requirement: non-field recipe needs matching station within range
  - policy offers craft_item only when something is craftable
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from world_state import build_world_state


def _info(inv=None, recipes=None, stations=None, nearby=None):
    return {
        "player": {"hp": 100, "maxHp": 100, "dead": False},
        "mana": 400, "maxMana": 471,
        "player_pos": [0, 0],
        "nearby": nearby or [],
        "inventory": inv or [],
        "recipes_known": recipes or [],
        "stations": stations or [],
        "quests": {"active": [], "ready": [], "done": []},
        "kills": 0, "deaths": 0,
    }


# ---------- observation ----------

def test_inv_by_id_counts_slots():
    info = _info(inv=[
        {"itemId": "rough_hide", "count": 20},
        {"itemId": "wolf_fang", "count": 13},
        {"itemId": "rough_hide", "count": 12},   # second stack of same item
    ])
    ws = build_world_state(info)
    assert ws["inv_by_id"] == {"rough_hide": 32, "wolf_fang": 13}


def test_craftable_now_field_recipe_with_reagents():
    recipe = {
        "id": "recipe_tanned_leather_jerkin",
        "resultItemId": "tanned_leather_jerkin",
        "reagents": [{"itemId": "rough_hide", "count": 30}],
        "stationType": None,          # field-craftable
    }
    info = _info(
        inv=[{"itemId": "rough_hide", "count": 32}],
        recipes=[recipe],
    )
    ws = build_world_state(info)
    c = [r["id"] for r in ws["craftable_now"]]
    assert c == ["recipe_tanned_leather_jerkin"], ws["craftable_now"]


def test_not_craftable_when_reagents_missing():
    recipe = {
        "id": "recipe_x",
        "resultItemId": "x_item",
        "reagents": [{"itemId": "wolf_fang", "count": 5}, {"itemId": "iron_ore", "count": 2}],
    }
    info = _info(inv=[{"itemId": "wolf_fang", "count": 13}], recipes=[recipe])
    ws = build_world_state(info)
    assert ws["craftable_now"] == []


def test_station_recipe_needs_station_nearby():
    rec = {
        "id": "recipe_forge_item",
        "resultItemId": "forge_item",
        "reagents": [{"itemId": "copper_ore", "count": 1}],
        "stationType": "forge",
    }
    stations = [{"id": "station_eastbrook_forge", "stationType": "forge", "x": 4.0, "z": 16.0}]
    # player at origin; forge is ~16.5u away -> out of interact range (8u)
    info = _info(inv=[{"itemId": "copper_ore", "count": 3}], recipes=[rec], stations=stations)
    ws = build_world_state(info)
    assert all(r["id"] != "recipe_forge_item" for r in ws["craftable_now"])
    # but it IS craftable when standing next to the forge
    info["player_pos"] = [4.0, 16.0]
    ws2 = build_world_state(info)
    assert any(r["id"] == "recipe_forge_item" for r in ws2["craftable_now"])


# ---------- policy ----------

from policy import GoalManager
from memory import ExperienceStore


def test_policy_offers_craft_only_when_craftable():
    gm = GoalManager(ExperienceStore())
    recipe = {
        "id": "recipe_tanned_leather_jerkin",
        "resultItemId": "tanned_leather_jerkin",
        "reagents": [{"itemId": "rough_hide", "count": 30}],
    }
    info = _info(inv=[{"itemId": "rough_hide", "count": 32}], recipes=[recipe])
    ws = build_world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "craft_item" in cands, cands
    # ctx must carry the chosen recipeId via decide()
    act, ctx = gm.decide(info, ws=ws, goal="DO_OBJECTIVE")
    if act == "craft_item":
        assert ctx.get("recipeId") == "recipe_tanned_leather_jerkin"


def test_policy_no_craft_without_materials():
    gm = GoalManager(ExperienceStore())
    info = _info()  # empty bags, no recipes
    ws = build_world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "craft_item" not in cands


# ---------- skills table ----------

def test_skills_table_has_craft_item():
    from hierarchical_env import SKILLS
    assert "craft_item" in SKILLS
