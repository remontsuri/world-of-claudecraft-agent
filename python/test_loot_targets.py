"""Тесты: лут — труп МОБА, а не декорация мира.

Живой баг (замер agent_run5.log): 153 шага подряд `loot -> inconclusive`.
Причина: флаг lootable в этой игре стоит и у объектов окружения —
'Ogre War Totem' (65 yd), 'Grave of Royal Assassin Voss' (25 yd),
'Warded Shore-Rock' (66 yd). Политика считала их лутом, звала loot,
мост ничего не делал.

Запуск: cd python && python -m pytest test_loot_targets.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory import ExperienceStore
from navigation import _matches
from observation import encode_observation
from policy import GoalManager
from world_state import build_world_state

# Ровно те сущности, что вернул живой мост
LIVE_DECOR = [
    {"kind": "object", "name": "Ogre War Totem", "dead": False,
     "lootable": True, "looted": False, "dist": 65.2, "pos": {"x": 65, "z": 0}},
    {"kind": "object", "name": "Grave of Royal Assassin Voss", "dead": False,
     "lootable": True, "looted": False, "dist": 25.2, "pos": {"x": 25, "z": 0}},
    {"kind": "object", "name": "Warded Shore-Rock", "dead": False,
     "lootable": True, "looted": False, "dist": 66.0, "pos": {"x": 66, "z": 0}},
]

DEAD_WOLF = {"kind": "mob", "name": "Forest Wolf", "templateId": "forest_wolf",
             "dead": True, "lootable": True, "looted": False, "hp": 0,
             "dist": 3.0, "pos": {"x": 3, "z": 0}}


def _info(nearby):
    return {
        "player": {"hp": 100, "maxHp": 100, "dead": False, "level": 3},
        "player_pos": [0.0, 0.0],
        "player_class": "warrior",
        "nearby": nearby,
        "inventory": [],
        "inventory_by_id": {},
        "equipment": {},
        "copper": 14,
        "quests": {"active": [], "ready": []},
    }


# ------------------------------------------------------- navigation._matches

def test_decor_is_not_a_corpse():
    for e in LIVE_DECOR:
        assert not _matches(e, "corpse"), e["name"]


def test_dead_mob_is_a_corpse():
    assert _matches(DEAD_WOLF, "corpse")


def test_explicit_corpse_kind_still_matches():
    assert _matches({"kind": "corpse", "looted": False}, "corpse")


def test_live_mob_is_not_a_corpse():
    assert not _matches(
        {"kind": "mob", "dead": False, "hp": 40, "lootable": False}, "corpse")


# ------------------------------------------------ observation.world.corpses

def test_observation_does_not_count_decor_as_corpses():
    obs = encode_observation(build_world_state(_info(LIVE_DECOR)),
                             _info(LIVE_DECOR))
    assert obs["world"]["corpses"] == 0


def test_observation_counts_a_dead_mob():
    nearby = LIVE_DECOR + [DEAD_WOLF]
    obs = encode_observation(build_world_state(_info(nearby)), _info(nearby))
    assert obs["world"]["corpses"] == 1


# ------------------------------------------------- policy candidate set

def _policy():
    return GoalManager(ExperienceStore(path="_test_loot_probe.json"),
                       temperature=1.0, seed=7)


def _cleanup():
    for p in ("_test_loot_probe.json",):
        if os.path.exists(p):
            os.unlink(p)


def test_policy_does_not_offer_loot_for_decor():
    """Главный тест: именно он ловит 153 холостых шага."""
    try:
        info = _info(LIVE_DECOR)
        cands = _policy()._candidates(info, build_world_state(info))
        assert "loot" not in cands, cands
    finally:
        _cleanup()


def test_policy_offers_loot_for_a_nearby_dead_mob():
    try:
        nearby = LIVE_DECOR + [DEAD_WOLF]
        info = _info(nearby)
        cands = _policy()._candidates(info, build_world_state(info))
        assert "loot" in cands, cands
    finally:
        _cleanup()


def test_policy_does_not_offer_loot_for_a_far_corpse():
    """Труп в 40 ярдах — работа навигации, а не повод звать loot."""
    try:
        far = dict(DEAD_WOLF, dist=40.0, pos={"x": 40, "z": 0})
        info = _info([far])
        cands = _policy()._candidates(info, build_world_state(info))
        assert "loot" not in cands, cands
    finally:
        _cleanup()
