"""Тесты Navigation Controller (ARCHITECTURE.md §6).

Запуск: cd python && python -m pytest test_navigation.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from navigation import (NavigationController, find_target, tolerance_for,
                        target_kind_for_subgoal,
                        ARRIVED, MOVING, STUCK, BLOCKED, TIMEOUT, NO_TARGET)


def _obs(px=0.0, pz=0.0, ents=None, dead=False):
    return {
        "player": {"position": [px, pz], "dead": dead, "hp_fraction": 1.0},
        "_entities": ents or [],
    }


def _giver(x, z, d=None):
    return {"kind": "npc", "questIds": ["q1"], "x": x, "z": z,
            "_dist": d if d is not None else (x ** 2 + z ** 2) ** 0.5}


def _vendor(x, z):
    return {"kind": "npc", "vendorItems": ["handaxe"], "x": x, "z": z,
            "_dist": (x ** 2 + z ** 2) ** 0.5}


def _mob(x, z, tid="forest_wolf", hp=10):
    return {"kind": "mob", "templateId": tid, "hp": hp, "x": x, "z": z,
            "_dist": (x ** 2 + z ** 2) ** 0.5}


# ------------------------------------------------------------ find_target

def test_find_nearest_giver():
    obs = _obs(ents=[_giver(30, 0), _giver(5, 0)])
    t = find_target(obs, "quest_giver")
    assert t["x"] == 5


def test_find_vendor_not_giver():
    obs = _obs(ents=[_giver(2, 0), _vendor(20, 0)])
    t = find_target(obs, "vendor")
    assert t["x"] == 20


def test_find_mob_respects_name_hint():
    obs = _obs(ents=[_mob(3, 0, "boar"), _mob(15, 0, "forest_wolf")])
    t = find_target(obs, "mob", "forest_wolf")
    assert t["x"] == 15


def test_dead_mob_is_not_a_target():
    obs = _obs(ents=[{"kind": "mob", "templateId": "wolf", "hp": 0,
                      "dead": True, "x": 2, "z": 0, "_dist": 2.0}])
    assert find_target(obs, "mob") is None


def test_entity_without_coords_is_skipped():
    obs = _obs(ents=[{"kind": "npc", "questIds": ["q"], "_dist": 3.0}])
    assert find_target(obs, "quest_giver") is None


def test_target_none_when_nothing_matches():
    assert find_target(_obs(), "quest_giver") is None


# ------------------------------------------------------------- tolerances

def test_giver_tolerance_is_inside_game_gate():
    # игра требует dist <= 7 (INTERACT_RANGE+2); допуск должен быть строже
    assert tolerance_for("quest_giver") < 7.0


def test_node_tolerance_inside_interact_range():
    assert tolerance_for("node") < 5.0


def test_vendor_tolerance_inside_buy_gate():
    assert tolerance_for("vendor") < 12.0


# ------------------------------------------------------------ status machine

def test_no_target_status():
    nav = NavigationController()
    assert nav.observe(_obs())["status"] == NO_TARGET


def test_arrived_when_within_tolerance():
    nav = NavigationController()
    obs = _obs(ents=[_giver(3, 0)])
    nav.set_target(obs, "quest_giver")
    assert nav.observe(obs)["status"] == ARRIVED


def test_moving_while_approaching():
    nav = NavigationController()
    obs = _obs(ents=[_giver(40, 0)])
    nav.set_target(obs, "quest_giver")
    assert nav.observe(obs)["status"] == MOVING
    # игрок сместился к цели
    assert nav.observe(_obs(px=10, ents=[_giver(40, 0)]))["status"] == MOVING


def test_stuck_when_position_frozen():
    nav = NavigationController()
    obs = _obs(ents=[_giver(40, 0)])
    nav.set_target(obs, "quest_giver")
    st = None
    for _ in range(5):
        st = nav.observe(obs)          # позиция не меняется
    assert st["status"] == STUCK
    assert nav.recovery_for(STUCK) == "unstuck_jump"


def test_blocked_when_moving_but_not_closer():
    nav = NavigationController(no_progress_limit=4)
    ents = [_giver(40, 0)]
    nav.set_target(_obs(ents=ents), "quest_giver")
    st = None
    # ходим по кругу: позиция меняется, дистанция нет
    ring = [(0, 5), (5, 0), (0, -5), (-5, 0)] * 3
    for (x, z) in ring:
        st = nav.observe(_obs(px=x, pz=z, ents=ents))
    assert st["status"] in (BLOCKED, STUCK)
    assert nav.recovery_for(BLOCKED) == "alternate_route"


def test_timeout_after_budget():
    nav = NavigationController(max_steps_per_target=3)
    ents = [_giver(60, 0)]
    nav.set_target(_obs(ents=ents), "quest_giver")
    st = None
    for i in range(3):
        st = nav.observe(_obs(px=i * 2, ents=ents))
    assert st["status"] == TIMEOUT
    assert nav.recovery_for(TIMEOUT) == "abandon_objective"


def test_budget_resets_only_on_target_kind_change():
    nav = NavigationController(max_steps_per_target=5)
    ents = [_giver(40, 0), _vendor(50, 0)]
    nav.set_target(_obs(ents=ents), "quest_giver")
    nav.observe(_obs(ents=ents))
    nav.observe(_obs(ents=ents))
    assert nav.steps == 2
    nav.set_target(_obs(ents=ents), "quest_giver")     # тот же тип
    assert nav.steps == 2
    nav.set_target(_obs(ents=ents), "vendor")          # другой тип
    assert nav.steps == 0


def test_nav_command_carries_game_coordinates():
    nav = NavigationController()
    obs = _obs(ents=[_giver(12.5, -7.25)])
    nav.set_target(obs, "quest_giver")
    cmd = nav.nav_command()
    assert cmd["action"] == "navigate"
    assert cmd["x"] == 12.5 and cmd["z"] == -7.25


def test_clear_drops_target():
    nav = NavigationController()
    nav.set_target(_obs(ents=[_giver(40, 0)]), "quest_giver")
    nav.clear()
    assert nav.observe(_obs())["status"] == NO_TARGET


# ------------------------------------------------------- subgoal -> target

def test_subgoal_target_kinds():
    assert target_kind_for_subgoal({"subgoal": "ACCEPT"}) == "quest_giver"
    assert target_kind_for_subgoal({"subgoal": "TURN_IN"}) == "quest_giver"
    assert target_kind_for_subgoal({"subgoal": "GET_TOOL"}) == "vendor"
    assert target_kind_for_subgoal({"subgoal": "GATHER"}) == "node"
    assert target_kind_for_subgoal({"subgoal": "KILL"}) == "mob"
    assert target_kind_for_subgoal({"subgoal": "LOOT"}) == "corpse"


def test_explicit_target_overrides_map():
    assert target_kind_for_subgoal(
        {"subgoal": "GO_TO_VENDOR", "target": "vendor"}) == "vendor"


def test_unknown_subgoal_has_no_target():
    assert target_kind_for_subgoal({"subgoal": "WAT"}) is None
    assert target_kind_for_subgoal(None) is None
