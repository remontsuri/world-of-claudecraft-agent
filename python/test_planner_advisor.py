"""test_planner_advisor.py — verify advisor_context returns correct structure.

Run: cd python && python -m pytest test_planner_advisor.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from planner import Planner


def _obs(hp=1.0, dead=False, free=5, junk=0, missing_tool=None,
         active=0, ready=0, nxt=None, giver_dist=999.0, givers=0,
         quest_available=False, mobs=0, nodes=0, vendor_dist=999.0,
         items=None):
    if quest_available:
        givers = max(1, givers)
        if giver_dist >= 999.0:
            giver_dist = 4.0
    return {
        "player": {"hp_fraction": hp, "dead": dead, "level": 1},
        "quest": {"active": active, "ready": ready, "next_objective": nxt,
                  "giver_distance": giver_dist},
        "inventory": {"free_slots": free, "junk_count": junk,
                      "missing_tool": missing_tool,
                      "items": items if items is not None else {"baked_bread": 2}},
        "world": {"nearby_mobs": mobs, "gather_nodes": nodes,
                  "quest_givers": givers, "quest_available": quest_available,
                  "vendor_distance": vendor_dist, "vendors": 1 if vendor_dist < 999 else 0},
        "navigation": {},
    }


def test_advisor_context_returns_dict_with_required_keys():
    p = Planner()
    obs = _obs(ready=1, giver_dist=3.0)
    ctx = p.advisor_context(obs)
    assert isinstance(ctx, dict)
    assert "subgoal" in ctx
    assert "target_mob_id" in ctx
    assert "node_type" in ctx
    assert "reason" in ctx


def test_advisor_context_turn_in():
    p = Planner()
    ctx = p.advisor_context(_obs(ready=1, giver_dist=3.0))
    assert ctx["subgoal"] == "TURN_IN"
    assert ctx["reason"] == "quest_ready"


def test_advisor_context_kill_with_target():
    p = Planner()
    nxt = {"type": "kill", "target_mob_id": "forest_wolf", "remaining": 5}
    ctx = p.advisor_context(_obs(active=1, nxt=nxt, mobs=2))
    assert ctx["subgoal"] == "KILL"
    assert ctx["target_mob_id"] == "forest_wolf"


def test_advisor_context_find_mob():
    p = Planner()
    nxt = {"type": "kill", "target_mob_id": "forest_wolf", "remaining": 5}
    ctx = p.advisor_context(_obs(active=1, nxt=nxt, mobs=0))
    assert ctx["subgoal"] == "FIND_MOB"
    assert ctx["target_mob_id"] == "forest_wolf"


def test_advisor_context_gather_with_node_type():
    p = Planner()
    nxt = {"type": "gather", "node_type": "wood", "item_id": "ironbark_log",
           "current": 0, "required": 8, "remaining": 8}
    ctx = p.advisor_context(_obs(active=1, nxt=nxt, nodes=1))
    assert ctx["subgoal"] == "GATHER"
    assert ctx["node_type"] == "wood"


def test_advisor_context_death():
    p = Planner()
    ctx = p.advisor_context(_obs(dead=True))
    assert ctx["subgoal"] == "RESPAWN"


def test_advisor_context_explore_when_idle():
    p = Planner()
    ctx = p.advisor_context(_obs())
    assert ctx["subgoal"] == "EXPLORE"


def test_advisor_context_accept_quest():
    p = Planner()
    ctx = p.advisor_context(_obs(quest_available=True))
    assert ctx["subgoal"] == "ACCEPT"


def test_advisor_context_does_not_force_skill():
    """advisor_context must return context, not force a skill choice."""
    p = Planner()
    # Even when FIND_MOB, advisor returns context — policy decides how to find
    nxt = {"type": "kill", "target_mob_id": "forest_wolf", "remaining": 5}
    ctx = p.advisor_context(_obs(active=1, nxt=nxt, mobs=0))
    assert ctx["subgoal"] == "FIND_MOB"
    # No "skill" key — advisor doesn't dictate HOW
    assert "skill" not in ctx
