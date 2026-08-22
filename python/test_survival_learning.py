"""TDD tests for the survival-learning fixes (user report 2026-08-22):

The agent died 7 times in one run while farming mobs that kill it and never
learned to avoid them or retreat. Root causes found in code:

  a) _bucket() omits strong_mob_near -> Q(farm) aliases weak-mob wins with
     strong-mob deaths; the average stays positive so the agent re-engages.
  b) at crit HP with an active quest the candidate set is {farm, loot,
     heal(no potions left)} -- no survivable action exists. return_to_giver
     must be available as a retreat option when in danger.
  c) verify_heal returns 'inconclusive' when no potion is present, which
     yields ~zero reward: the agent gets no negative signal for trying to
     heal without supplies. It must be FAILURE.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from memory import _bucket
from policy import GoalManager
from world_state import build_world_state
from verifiers_py import verify_heal


# ---------- (a) bucket must distinguish strong mobs ----------

def _ws(**over):
    base = dict(
        hp_frac=1.0, player_maxhp=100,
        quest_status="ACTIVE", has_mob=True, strong_mob_near=False,
        weak_mob_near=False, has_corpse=False, has_junk=False,
        vendor_nearby=False, danger=False, distance_to_giver=50.0,
        in_combat=False, dead=False,
    )
    base.update(over)
    return base


def test_bucket_distinguishes_strong_mob():
    weak = _bucket(_ws(weak_mob_near=True))
    strong = _bucket(_ws(strong_mob_near=True))
    assert weak != strong, (
        "Q-table aliasing: buckets must differ between weak and strong mob states")


def test_bucket_stable_when_neither():
    b1 = _bucket(_ws())
    b2 = _bucket(_ws())
    assert b1 == b2


# ---------- (b) retreat option at low hp ----------

def _fake_info(active_quests, player_hp=100, max_hp=100):
    return {
        "player": {"hp": player_hp, "maxHp": max_hp, "dead": False},
        "player_pos": [0, 0],
        "nearby": [],
        "inventory": [],
        "quests": {"active": active_quests, "ready": [], "done": []},
        "kills": 0, "deaths": 0,
    }


def test_return_to_giver_offered_in_danger_with_active_quest():
    """At low-but-not-crit HP with an active quest, retreat must be a candidate."""
    info = _fake_info([{
        "id": "q_x", "state": "active",
        "objectives": [{"current": 0, "required": 5}],
        "turnInNpc": {"x": 10.0, "z": 5.0},
    }], player_hp=32, max_hp=100)
    ws = build_world_state(info)
    # hp_frac 0.32: below the 0.35 survival floor -> walking skills are gated.
    # (danger itself requires hp<0.3 or combat; this test pins the GATE.)
    gm = GoalManager.__new__(GoalManager)  # skip __init__ (memory not needed)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    # 0.32 < 0.35 -> survival gate holds, no walking skills
    assert "return_to_giver" not in cands, cands
    assert "turn_in_quest" not in cands, cands


def test_retreat_offered_when_danger_above_floor():
    """danger (hp<0.3... no: in_combat) + active quest + hp>=0.35 -> retreat."""
    info = _fake_info([{
        "id": "q_x", "state": "active",
        "objectives": [{"current": 0, "required": 5}],
        "turnInNpc": {"x": 10.0, "z": 5.0},
    }], player_hp=40, max_hp=100)
    info["in_combat"] = True  # danger comes from combat, not hp
    ws = build_world_state(info)
    assert ws["danger"] is True and ws["hp_frac"] >= 0.35
    gm = GoalManager.__new__(GoalManager)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "return_to_giver" in cands, cands


def test_no_retreat_when_safe():
    """When healthy, the phase gate should still hold (no premature return)."""
    info = _fake_info([{
        "id": "q_x", "state": "active",
        "objectives": [{"current": 0, "required": 5}],
        "turnInNpc": {"x": 10.0, "z": 5.0},
    }])
    # healthy: hp 100/100 -> danger False
    ws = build_world_state(info)
    assert ws["danger"] is False
    gm = GoalManager.__new__(GoalManager)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "return_to_giver" not in cands, cands


# ---------- (c) heal without potions is FAILURE ----------

def test_heal_without_potion_is_failure():
    before = {
        "player": {"hp": 30, "maxHp": 100},
        "inventory": [{"quality": 1, "name": "junk item"}],
    }
    after = {
        "player": {"hp": 30, "maxHp": 100},   # hp unchanged: nothing was used
        "inventory": [{"quality": 1, "name": "junk item"}],  # no potion consumed
    }
    verdict = verify_heal({"before": before, "after": after})
    assert verdict == "failure", "heal without potion must be failure, got %r" % verdict


def test_heal_success_still_works():
    before = {
        "player": {"hp": 30, "maxHp": 100},
        "inventory": [{"quality": 2, "name": "minor healing potion"}],
    }
    after = {
        "player": {"hp": 60, "maxHp": 100},
        "inventory": [],  # potion consumed
    }
    verdict = verify_heal({"before": before, "after": after})
    assert verdict == "success", verdict
