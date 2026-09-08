"""test_autonomy_no_force.py — verify before_action doesn't force skills.

Run: cd python && python -m pytest test_autonomy_no_force.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autonomy import AutonomyLoop


def _info(hp=100, maxhp=100, copper=0, kills=0, deaths=0, dead=False,
          nearby=None, quests=None, inv=None):
    return {
        "player": {"hp": hp, "maxHp": maxhp, "level": 1, "dead": dead,
                   "pos": {"x": 0.0, "z": 0.0}},
        "player_pos": [0.0, 0.0],
        "player_class": "warrior",
        "nearby": nearby if nearby is not None else [],
        "quests": quests if quests is not None else {"active": [], "done": []},
        "inventory": inv if inv is not None else [],
        "copper": copper, "kills": kills, "deaths": deaths, "xp": 0,
    }


def _ws(info, **over):
    """Минимальный ws: контур толерантен, ему хватает info + пары полей."""
    ws = dict(info)
    ws["hp_frac"] = info["player"]["hp"] / max(1, info["player"]["maxHp"])
    ws["bag_capacity"] = 26
    ws.update(over)
    return ws


def test_before_action_returns_advisor():
    loop = AutonomyLoop()
    info = _info()
    out = loop.before_action(info, _ws(info), ["farm", "buy", "gather"])
    assert "advisor" in out
    assert isinstance(out["advisor"], dict)
    assert "subgoal" in out["advisor"]


def test_before_action_no_force_explore_for_find_mob():
    """When planner says FIND_MOB, before_action must NOT force explore."""
    loop = AutonomyLoop()
    # kill objective with no mobs nearby -> planner says FIND_MOB
    info = _info(quests={"active": [{"id": "q1", "objectives": [
        {"type": "kill", "targetMobId": "forest_wolf", "current": 0, "required": 5}
    ]}], "done": []})
    out = loop.before_action(info, _ws(info), ["farm", "explore", "loot"])
    # The advisor should say FIND_MOB, but the candidates should not be
    # forced to only explore — policy decides
    assert out["advisor"]["subgoal"] == "FIND_MOB"
    # Candidates should still include explore (policy may choose)
    assert "explore" in out["candidates"]


def test_before_action_no_anchor_force():
    """When agent is far from giver, before_action must NOT force return_to_giver."""
    loop = AutonomyLoop()
    info = _info(quests={"active": [{"id": "q1", "objectives": [
        {"type": "kill", "targetMobId": "wolf", "current": 0, "required": 3}
    ]}], "done": []})
    ws = _ws(info, distance_to_giver=100.0)
    out = loop.before_action(info, ws, ["farm", "explore", "return_to_giver"])
    # No anchor_needed signal should be present
    signals = out.get("signals") or {}
    assert "anchor_needed" not in signals


def test_before_action_masks_candidates():
    """before_action should still mask candidates by preconditions."""
    loop = AutonomyLoop()
    # buy requires a vendor nearby -> should be masked out when no vendor
    info = _info(nearby=[{"kind": "mob", "hp": 10, "level": 1, "dist": 6.0, "x": 5.0, "z": 0.0}])
    out = loop.before_action(info, _ws(info), ["buy", "farm", "explore"])
    # buy should be masked out (no vendor nearby)
    assert "buy" not in out["candidates"]
    # farm should pass (mob nearby)
    assert "farm" in out["candidates"]


def test_before_action_builds_decision_context():
    """before_action should still build a DecisionContext."""
    loop = AutonomyLoop()
    info = _info()
    out = loop.before_action(info, _ws(info), ["farm", "explore"])
    assert "decision_context" in out
    dc = out["decision_context"]
    assert dc.subgoal is not None


def test_before_action_no_subgoal_nav_signal():
    """When no recovery/loop, before_action should NOT emit subgoal_nav signal."""
    loop = AutonomyLoop()
    info = _info(quests={"active": [{"id": "q1", "objectives": [
        {"type": "kill", "targetMobId": "forest_wolf", "current": 0, "required": 5}
    ]}], "done": []})
    out = loop.before_action(info, _ws(info), ["farm", "explore", "loot"])
    signals = out.get("signals") or {}
    assert "subgoal_nav" not in signals
