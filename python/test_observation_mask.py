"""Тесты Observation Encoder и Action Mask (ARCHITECTURE.md §2, §4).

Запуск: cd python && python -m pytest test_observation_mask.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from observation import encode_observation
from action_mask import (get_action_mask, available_actions, mask_candidates,
                        why_blocked, index_of, SKILL_INDEX)


# ---------------------------------------------------------------- observation

def test_hp_fraction_computed():
    ws = {"player": {"hp": 80, "maxHp": 100, "level": 1}}
    obs = encode_observation(ws)
    assert obs["player"]["hp_fraction"] == 0.8


def test_player_class_passthrough():
    obs = encode_observation({"player_class": "warrior", "player": {"maxHp": 1}})
    assert obs["player"]["player_class"] == "warrior"


def test_all_six_blocks_present():
    obs = encode_observation({"player": {"maxHp": 1}})
    for block in ("player", "target", "quest", "inventory", "world", "navigation"):
        assert block in obs, block


def test_target_from_nearest_live_mob():
    ws = {
        "player": {"hp": 100, "maxHp": 100, "level": 3},
        "player_pos": [0.0, 0.0],
        "nearby": [
            {"kind": "mob", "templateId": "forest_wolf", "hp": 30, "level": 4, "dist": 12.0},
            {"kind": "mob", "templateId": "boar", "hp": 20, "level": 2, "dist": 3.0},
        ],
    }
    obs = encode_observation(ws)
    assert obs["target"]["exists"] is True
    assert obs["target"]["mob_id"] == "boar"       # ближайший
    assert obs["target"]["distance"] == 3.0
    assert obs["target"]["in_melee_range"] is True
    assert obs["target"]["level_diff"] == -1.0
    assert obs["world"]["nearby_mobs"] == 2


def test_dead_mob_is_corpse_not_target():
    ws = {"player": {"maxHp": 1}, "player_pos": [0, 0],
          "nearby": [{"kind": "mob", "dead": True, "hp": 0, "dist": 2.0}]}
    obs = encode_observation(ws)
    assert obs["target"]["exists"] is False
    assert obs["world"]["corpses"] == 1


def test_vendor_and_giver_detected_separately():
    ws = {"player": {"maxHp": 1}, "player_pos": [0, 0], "nearby": [
        {"kind": "npc", "name": "Trader Wilkes", "vendorItems": ["handaxe"], "dist": 8.0},
        {"kind": "npc", "name": "Marshal", "questIds": ["q_wolves"], "dist": 4.0},
    ]}
    obs = encode_observation(ws)
    assert obs["world"]["vendors"] == 1
    assert obs["world"]["vendor_distance"] == 8.0
    assert obs["world"]["quest_givers"] == 1
    assert obs["quest"]["giver_distance"] == 4.0
    assert obs["world"]["quest_available"] is True   # 4.0 <= 7


def test_next_objective_is_first_incomplete():
    ws = {"player": {"maxHp": 1}, "quests": {"active": [{
        "id": "q_wolves",
        "objectives": [
            {"type": "kill", "targetMobId": "forest_wolf", "current": 8, "required": 8},
            {"type": "gather", "nodeType": "wood", "itemId": "ironbark_log",
             "current": 2, "required": 6},
        ],
    }]}}
    obs = encode_observation(ws)
    nxt = obs["quest"]["next_objective"]
    assert nxt["type"] == "gather"
    assert nxt["remaining"] == 4
    assert obs["quest"]["objective_progress"] == 2
    assert obs["quest"]["objective_required"] == 6


def test_ready_derived_from_active_state():
    ws = {"player": {"maxHp": 1},
          "quests": {"active": [{"id": "q1", "state": "ready"}]}}
    obs = encode_observation(ws)
    assert obs["quest"]["ready"] == 1


def test_junk_counted_from_inventory_quality():
    ws = {"player": {"maxHp": 1},
          "inventory": [{"quality": 0}, {"quality": 0}, {"quality": 2}]}
    obs = encode_observation(ws)
    assert obs["inventory"]["junk_count"] == 2


def test_free_slots_from_capacity_when_not_given():
    ws = {"player": {"maxHp": 1}, "bag_capacity": 26,
          "inventory": [{"quality": 1}] * 20}
    obs = encode_observation(ws)
    assert obs["inventory"]["free_slots"] == 6


def test_encoder_survives_empty_input():
    obs = encode_observation({})
    assert obs["player"]["hp_fraction"] == 0.0
    assert obs["target"]["exists"] is False
    assert obs["world"]["nearby_mobs"] == 0


def test_encoder_reads_info_fallback():
    obs = encode_observation({}, {"player": {"hp": 50, "maxHp": 100},
                                  "copper": 14, "player_class": "warrior"})
    assert obs["player"]["hp_fraction"] == 0.5
    assert obs["player"]["copper"] == 14
    assert obs["player"]["player_class"] == "warrior"


# --------------------------------------------------------------- action mask

def _obs(**over):
    base = {
        "player": {"hp_fraction": 1.0, "copper": 0, "level": 1},
        "target": {"distance": 999.0},
        "quest": {"ready": 0, "giver_distance": 999.0},
        "inventory": {"free_slots": 5, "junk_count": 0, "missing_tool": None},
        "world": {"vendors": 0, "gather_nodes": 0, "nearby_mobs": 0,
                  "corpses": 0, "quest_givers": 0, "vendor_distance": 999.0,
                  "node_distance": 999.0, "corpse_distance": 999.0,
                  "quest_available": False},
        "navigation": {"target_distance": 999.0},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k].update(v)
        else:
            base[k] = v
    return base


def test_mask_length_matches_bridge_indices():
    assert len(get_action_mask(_obs())) == len(SKILL_INDEX) == 10


def test_buy_masked_without_vendor():
    mask = get_action_mask(_obs())
    assert mask[index_of("buy")] == 0
    assert "vendor_exists" in why_blocked("buy", _obs())


def test_buy_unmasked_with_vendor_and_money():
    obs = _obs(world={"vendors": 1, "vendor_distance": 5.0},
               player={"copper": 50},
               inventory={"free_slots": 4})
    assert get_action_mask(obs)[index_of("buy")] == 1


def test_turn_in_masked_until_quest_ready():
    obs = _obs(world={"quest_givers": 1}, quest={"ready": 0, "giver_distance": 3.0})
    assert get_action_mask(obs)[index_of("turn_in_quest")] == 0
    obs = _obs(world={"quest_givers": 1}, quest={"ready": 1, "giver_distance": 3.0})
    assert get_action_mask(obs)[index_of("turn_in_quest")] == 1


def test_gather_masked_without_node_or_tool():
    obs = _obs(world={"gather_nodes": 1, "node_distance": 3.0},
               inventory={"missing_tool": "handaxe"})
    assert get_action_mask(obs)[index_of("gather")] == 0
    assert "has_tool" in why_blocked("gather", obs)


def test_heal_masked_at_full_hp():
    assert get_action_mask(_obs())[index_of("heal")] == 0
    assert get_action_mask(_obs(player={"hp_fraction": 0.4}))[index_of("heal")] == 1


def test_farm_masked_when_hp_critical():
    obs = _obs(world={"nearby_mobs": 1}, target={"distance": 10.0},
               player={"hp_fraction": 0.2})
    assert get_action_mask(obs)[index_of("farm")] == 0
    assert "hp_sufficient" in why_blocked("farm", obs)


def test_available_actions_falls_back_to_explore():
    assert available_actions(_obs()) == ["explore"]


def test_mask_candidates_never_empty():
    assert mask_candidates(["buy", "gather"], _obs()) == ["explore"]


def test_mask_candidates_keeps_valid_ones():
    obs = _obs(world={"nearby_mobs": 1}, target={"distance": 8.0})
    assert mask_candidates(["farm", "buy"], obs) == ["farm"]
