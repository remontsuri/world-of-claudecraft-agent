"""test_autonomy_no_force.py — verify before_action doesn't force skills.

Phase 5: before_action is now a thin wrapper that:
- Returns candidates unchanged
- Returns signals=None
- Returns decision_context=None
- ArbitrationLayer handles all forcing
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
    ws = dict(info)
    ws["hp_frac"] = info["player"]["hp"] / max(1, info["player"]["maxHp"])
    ws["bag_capacity"] = 26
    ws.update(over)
    return ws


def test_before_action_returns_advisor():
    """Phase 5: before_action still returns advisor context."""
    loop = AutonomyLoop()
    info = _info()
    out = loop.before_action(info, _ws(info), ["farm", "buy", "gather"])
    assert "advisor" in out
    assert isinstance(out["advisor"], dict)
    assert "subgoal" in out["advisor"]


def test_before_action_no_force_explore_for_find_mob():
    """Phase 5: When planner says FIND_MOB, before_action must NOT force explore."""
    loop = AutonomyLoop()
    info = _info(quests={"active": [{"id": "q1", "objectives": [
        {"type": "kill", "targetMobId": "forest_wolf", "current": 0, "required": 5}
    ]}], "done": []})
    out = loop.before_action(info, _ws(info), ["farm", "explore", "loot"])
    # The advisor should say FIND_MOB
    assert out["advisor"]["subgoal"] == "FIND_MOB"
    # Candidates should still include explore (policy may choose)
    assert "explore" in out["candidates"]


def test_before_action_no_anchor_force():
    """Phase 5: When agent is far from giver, before_action must NOT force return_to_giver."""
    loop = AutonomyLoop()
    info = _info(quests={"active": [{"id": "q1", "objectives": [
        {"type": "kill", "targetMobId": "wolf", "current": 0, "required": 3}
    ]}], "done": []})
    ws = _ws(info, distance_to_giver=100.0)
    out = loop.before_action(info, ws, ["farm", "explore", "return_to_giver"])
    # No anchor_needed signal should be present (thin wrapper doesn't detect)
    signals = out.get("signals") or {}
    assert "anchor_needed" not in signals


def test_before_action_passes_candidates_through():
    """Phase 5: before_action no longer masks candidates."""
    loop = AutonomyLoop()
    info = _info(nearby=[{"kind": "mob", "hp": 10, "level": 1, "dist": 6.0, "x": 5.0, "z": 0.0}])
    out = loop.before_action(info, _ws(info), ["buy", "farm", "explore"])
    # Candidates are passed through unchanged
    assert "buy" in out["candidates"]
    assert "farm" in out["candidates"]
    assert "explore" in out["candidates"]


def test_before_action_no_decision_context():
    """Phase 5: before_action no longer builds DecisionContext."""
    loop = AutonomyLoop()
    info = _info()
    out = loop.before_action(info, _ws(info), ["farm", "explore"])
    # decision_context is None in thin wrapper
    assert out["decision_context"] is None


def test_before_action_no_subgoal_nav_signal():
    """Phase 5: before_action should NOT emit any signals."""
    loop = AutonomyLoop()
    info = _info(quests={"active": [{"id": "q1", "objectives": [
        {"type": "kill", "targetMobId": "forest_wolf", "current": 0, "required": 5}
    ]}], "done": []})
    out = loop.before_action(info, _ws(info), ["farm", "explore", "loot"])
    # Signals is None in thin wrapper
    assert out["signals"] is None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
