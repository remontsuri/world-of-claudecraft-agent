"""Тесты выбора цели боя: квестовый моб vs ближайший (аудит P0.5).

Запуск: cd python && python -m pytest test_quest_target.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from observation import _mob_matches, _pick_target, encode_observation


def _mob(name, dist, template=None):
    return {"kind": "mob", "name": name, "templateId": template,
            "dist": dist, "_dist": dist, "hp": 50, "x": dist, "z": 0.0}


# --------------------------------------------------------------- matching

def test_matches_human_name_against_snake_id():
    assert _mob_matches(_mob("Forest Wolf", 5), "forest_wolf")


def test_matches_template_id_directly():
    assert _mob_matches(_mob("whatever", 5, "forest_wolf"), "forest_wolf")


def test_does_not_match_different_mob():
    assert not _mob_matches(_mob("Boar", 5), "forest_wolf")


def test_no_hint_never_matches():
    assert not _mob_matches(_mob("Boar", 5), None)


# ------------------------------------------------------------ target pick

def test_nearest_when_no_quest_target():
    mobs = [_mob("Boar", 4.0), _mob("Forest Wolf", 12.0)]
    assert _pick_target(mobs, None)["name"] == "Boar"


def test_quest_mob_wins_over_nearer_mob():
    """Ключевой кейс ревью: кабан 4 yd, квестовый волк 12 yd."""
    mobs = [_mob("Boar", 4.0), _mob("Forest Wolf", 12.0)]
    assert _pick_target(mobs, "forest_wolf")["name"] == "Forest Wolf"


def test_nearest_quest_mob_when_several():
    mobs = [_mob("Forest Wolf", 20.0), _mob("Boar", 4.0),
            _mob("Forest Wolf", 9.0)]
    picked = _pick_target(mobs, "forest_wolf")
    assert picked["name"] == "Forest Wolf" and picked["_dist"] == 9.0


def test_falls_back_to_nearest_when_quest_mob_absent():
    mobs = [_mob("Boar", 4.0)]
    assert _pick_target(mobs, "forest_wolf")["name"] == "Boar"


def test_empty_world_has_no_target():
    assert _pick_target([], "forest_wolf") is None


# ------------------------------------------------- через encode_observation

def _info(mobs, objective=None):
    quests = {"active": [], "ready": [], "done": []}
    if objective:
        quests["active"] = [{
            "questId": "q_wolves", "state": "active",
            "objectives": [objective],
        }]
    return {
        "player": {"hp": 100, "maxHp": 100, "level": 1, "dead": False,
                   "pos": {"x": 0.0, "z": 0.0}, "xp": 0},
        "player_pos": [0.0, 0.0], "player_class": "warrior",
        "nearby": mobs, "quests": quests, "inventory": [],
        "inventory_by_id": {}, "equipment": {},
        "copper": 0, "kills": 0, "deaths": 0, "xp": 0, "bagCapacity": 16,
    }


def _ws(info):
    ws = dict(info)
    ws["hp_frac"] = 1.0
    ws["bag_capacity"] = 16
    return ws


def test_observation_targets_quest_mob_not_nearest():
    mobs = [_mob("Boar", 4.0), _mob("Forest Wolf", 12.0)]
    info = _info(mobs, {"type": "kill", "targetMobId": "forest_wolf",
                        "current": 0, "required": 8})
    obs = encode_observation(_ws(info), info)
    t = obs["target"]
    assert t["quest_mob_id"] == "forest_wolf"
    assert t["is_quest_target"] is True
    assert t["distance"] == 12.0, "должен смотреть на волка, а не на кабана"


def test_observation_uses_nearest_without_kill_objective():
    mobs = [_mob("Boar", 4.0), _mob("Forest Wolf", 12.0)]
    info = _info(mobs, {"type": "gather", "nodeType": "wood",
                        "current": 0, "required": 8})
    obs = encode_observation(_ws(info), info)
    assert obs["target"]["distance"] == 4.0
    assert obs["target"]["is_quest_target"] is False


def test_observation_no_objective_falls_back_to_nearest():
    mobs = [_mob("Boar", 4.0)]
    info = _info(mobs)
    obs = encode_observation(_ws(info), info)
    assert obs["target"]["distance"] == 4.0
    assert obs["target"]["quest_mob_id"] is None
