"""Тесты исполнения recovery и отказа от цели (аудит P0.6, P0.7).

Ревью: «AutonomyLoop не исполняет recovery — он только возвращает его»
и «abandon_objective фактически не action».

Запуск: cd python && python -m pytest test_recovery_execution.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autonomy import AutonomyLoop
from recovery import (ObjectiveBlacklist, RECOVERY_LADDER, DEFAULT_LADDER,
                      assert_recovery_executable, plan_recovery)


# ------------------------------------------------- каждая ветка исполнима

def test_every_recovery_action_has_an_implementation():
    """Ни одна стратегия не должна быть «только записью в лог»."""
    actions = assert_recovery_executable()
    assert len(actions) >= 25


def test_recovery_maps_to_skill():
    p = plan_recovery("buy_tool")
    assert p["kind"] == "skill" and p["skill"] == "buy"


def test_recovery_maps_to_navigation():
    p = plan_recovery("navigate_to_giver")
    assert p["kind"] == "navigate" and p["target"] == "quest_giver"


def test_recovery_maps_to_control():
    assert plan_recovery("abandon_objective") == {
        "kind": "control", "op": "abandon", "action": "abandon_objective"}


def test_unknown_recovery_never_returns_nothing():
    """Неизвестная стратегия -> replan, а не молчаливое None."""
    p = plan_recovery("no_such_strategy")
    assert p["kind"] == "control" and p["op"] == "replan"


def test_every_ladder_entry_is_mapped():
    known = set(DEFAULT_LADDER)
    for ladder in RECOVERY_LADDER.values():
        known.update(ladder)
    for a in known:
        assert plan_recovery(a)["action"] == a


# --------------------------------------------------------- blacklist P0.7

def test_abandon_blocks_objective():
    bl = ObjectiveBlacklist(cooldown_steps=10)
    bl.abandon("q_wolves:kill:forest_wolf", "mob_too_far")
    assert bl.is_blocked("q_wolves:kill:forest_wolf")


def test_abandon_blocks_regardless_of_reason():
    """Цель недостижима как таковая, а не только по одной причине."""
    bl = ObjectiveBlacklist(cooldown_steps=10)
    bl.abandon("q:kill:wolf", "mob_too_far")
    assert bl.is_blocked("q:kill:wolf", "no_mob")


def test_cooldown_expires():
    bl = ObjectiveBlacklist(cooldown_steps=3)
    bl.abandon("q:kill:wolf", "no_mob")
    for _ in range(3):
        bl.tick()
    assert not bl.is_blocked("q:kill:wolf")


def test_other_objectives_stay_available():
    bl = ObjectiveBlacklist(cooldown_steps=10)
    bl.abandon("q:kill:wolf", "no_mob")
    assert not bl.is_blocked("q:gather:wood")


def test_none_objective_is_never_blocked():
    bl = ObjectiveBlacklist()
    bl.abandon(None, "whatever")
    assert not bl.is_blocked(None)


# ----------------------------------------------- исполнение внутри контура

def _info(dead=False, hp=100, giver_dist=None, mobs=0):
    nearby = []
    if giver_dist is not None:
        nearby.append({"kind": "npc", "name": "Marshal", "questIds": ["q1"],
                       "dist": giver_dist, "x": giver_dist, "z": 0.0})
    for k in range(mobs):
        nearby.append({"kind": "mob", "name": "Boar", "hp": 40,
                       "dist": 30.0 + k, "x": 30.0 + k, "z": 0.0})
    return {
        "player": {"hp": hp, "maxHp": 100, "level": 1, "dead": dead,
                   "pos": {"x": 0.0, "z": 0.0}, "xp": 0},
        "player_pos": [0.0, 0.0], "player_class": "warrior",
        "nearby": nearby, "quests": {"active": [], "ready": [], "done": []},
        "inventory": [], "inventory_by_id": {}, "equipment": {},
        "copper": 0, "kills": 0, "deaths": 0, "xp": 0, "bagCapacity": 16,
        "quest_states": {"q1": "available"},  # FIX #1: квест доступен
    }


def _ws(info):
    ws = dict(info)
    ws["hp_frac"] = (info["player"]["hp"] or 0) / 100.0
    ws["bag_capacity"] = 16
    return ws


def test_loop_executes_pending_recovery_next_step():
    """FAILURE -> recovery -> на следующем шаге контур это ДЕЛАЕТ."""
    loop = AutonomyLoop(min_dwell=1)
    info = _info(giver_dist=40.0)

    loop.before_action(info, _ws(info), ["accept_quest", "farm", "explore"])
    loop.after_action("accept_quest", info, _ws(info))

    assert loop.pending_recovery is not None, "recovery должен быть запланирован"
    pre = loop.before_action(info, _ws(info), ["accept_quest", "farm", "explore"])
    assert loop.stats.get("recoveries_executed", 0) >= 1
    assert loop.pending_recovery is None, "исполненный recovery не должен залипать"


def test_abandon_marks_objective_and_forces_replan():
    loop = AutonomyLoop(min_dwell=20)
    info = _info(mobs=1)
    obs = loop.before_action(info, _ws(info), ["farm"])["obs"]

    key = loop._objective_key(obs)
    loop.blacklist.abandon(key or "x:kill:y", "no_mob")
    loop.planner.force_replan()
    assert loop.planner.current is None, "force_replan должен снять удержание цели"


def test_success_clears_pending_recovery():
    loop = AutonomyLoop(min_dwell=1)
    info = _info(mobs=1)
    loop.before_action(info, _ws(info), ["farm"])
    loop.pending_recovery = {"kind": "skill", "skill": "farm"}

    after = _info(mobs=1)
    after["kills"] = 1
    loop.after_action("farm", after, _ws(after))
    assert loop.pending_recovery is None
