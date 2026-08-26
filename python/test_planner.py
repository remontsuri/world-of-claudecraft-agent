"""Тесты Planner (ARCHITECTURE.md §5).

Запуск: cd python && python -m pytest test_planner.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from planner import (plan_subgoals, current_subgoal, required_tool, Planner,
                     TOOL_FOR_NODE)


def _obs(hp=1.0, dead=False, free=5, junk=0, missing_tool=None,
         active=0, ready=0, nxt=None, giver_dist=999.0, givers=0,
         quest_available=False, mobs=0, nodes=0, vendor_dist=999.0,
         items=None):
    # quest_available подразумевает, что гивер есть и он в радиусе
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
                      # чем лечиться: без еды/зелий heal — no-op, и план
                      # уходит в REGEN вместо бесполезного SURVIVE
                      "items": items if items is not None else {"baked_bread": 2}},
        "world": {"nearby_mobs": mobs, "gather_nodes": nodes,
                  "quest_givers": givers, "quest_available": quest_available,
                  "vendor_distance": vendor_dist, "vendors": 1 if vendor_dist < 999 else 0},
        "navigation": {},
    }


# ------------------------------------------------------------- tool mapping

def test_tool_for_wood_is_handaxe_not_logging_axe():
    # logging_axe В ИГРЕ НЕ СУЩЕСТВУЕТ — реальный предмет handaxe
    assert required_tool({"node_type": "wood"}) == "handaxe"
    assert "logging_axe" not in TOOL_FOR_NODE.values()


def test_tool_for_herb_is_gathering_sickle():
    assert required_tool({"node_type": "herb"}) == "gathering_sickle"
    assert "herb_sack" not in TOOL_FOR_NODE.values()


def test_tool_from_item_id_when_node_type_missing():
    assert required_tool({"item_id": "ironbark_log"}) == "handaxe"
    assert required_tool({"item_id": "copper_ore"}) == "copper_mining_pick"


def test_tool_none_for_kill_objective():
    assert required_tool({"type": "kill", "target_mob_id": "forest_wolf"}) is None


# --------------------------------------------------------------- priorities

def test_death_wins_over_everything():
    obs = _obs(dead=True, ready=1, giver_dist=2.0)
    assert plan_subgoals(obs)[0]["subgoal"] == "RESPAWN"


def test_critical_hp_beats_quest_turnin():
    obs = _obs(hp=0.2, ready=1, giver_dist=2.0)
    assert plan_subgoals(obs)[0]["subgoal"] == "SURVIVE"


def test_full_bags_go_sell_first():
    plan = plan_subgoals(_obs(free=0, junk=5))
    assert [p["subgoal"] for p in plan] == ["GO_TO_VENDOR", "SELL"]


def test_ready_quest_near_giver_turns_in_directly():
    plan = plan_subgoals(_obs(ready=1, giver_dist=3.0))
    assert plan[0]["subgoal"] == "TURN_IN"


def test_ready_quest_far_giver_navigates_first():
    plan = plan_subgoals(_obs(ready=1, giver_dist=40.0))
    assert [p["subgoal"] for p in plan] == ["RETURN_TO_GIVER", "TURN_IN"]


# ------------------------------------------------------- objective planning

def test_gather_objective_buys_tool_before_gathering():
    nxt = {"type": "gather", "node_type": "wood", "item_id": "ironbark_log",
           "current": 0, "required": 8, "remaining": 8}
    plan = plan_subgoals(_obs(active=1, nxt=nxt, missing_tool="handaxe",
                              vendor_dist=30.0))
    names = [p["subgoal"] for p in plan]
    assert names.index("GET_TOOL") < names.index("GATHER")
    assert names[0] == "GO_TO_VENDOR"        # вендор далеко -> сначала дойти
    assert plan[names.index("GET_TOOL")]["item"] == "handaxe"
    assert names[-1] == "TURN_IN"


def test_gather_with_tool_in_hand_skips_buying():
    nxt = {"type": "gather", "node_type": "wood", "current": 2, "required": 6,
           "remaining": 4}
    plan = plan_subgoals(_obs(active=1, nxt=nxt, nodes=1))
    names = [p["subgoal"] for p in plan]
    assert "GET_TOOL" not in names
    assert names[0] == "GATHER"
    assert plan[0]["count"] == 4


def test_gather_without_node_in_range_navigates():
    nxt = {"type": "gather", "node_type": "ore", "remaining": 3}
    plan = plan_subgoals(_obs(active=1, nxt=nxt, nodes=0))
    assert plan[0]["subgoal"] == "GO_TO_NODE"


def test_kill_objective_carries_target_mob_id():
    nxt = {"type": "kill", "target_mob_id": "forest_wolf", "remaining": 5}
    plan = plan_subgoals(_obs(active=1, nxt=nxt, mobs=2))
    kill = next(p for p in plan if p["subgoal"] == "KILL")
    assert kill["target_mob_id"] == "forest_wolf"
    assert kill["count"] == 5
    assert any(p["subgoal"] == "LOOT" for p in plan)


def test_kill_without_mob_in_range_explores_first():
    nxt = {"type": "kill", "target_mob_id": "forest_wolf", "remaining": 5}
    plan = plan_subgoals(_obs(active=1, nxt=nxt, mobs=0))
    assert plan[0]["subgoal"] == "FIND_MOB"


def test_unknown_objective_type_does_not_crash():
    nxt = {"type": "weird_new_type", "remaining": 1}
    plan = plan_subgoals(_obs(active=1, nxt=nxt))
    assert plan  # план не пустой
    assert plan[-1]["subgoal"] == "TURN_IN"


# -------------------------------------------------------------- accept/idle

def test_accepts_quest_when_giver_in_range():
    assert plan_subgoals(_obs(quest_available=True))[0]["subgoal"] == "ACCEPT"


def test_walks_to_giver_when_out_of_range():
    plan = plan_subgoals(_obs(givers=1, quest_available=False))
    assert [p["subgoal"] for p in plan] == ["GO_TO_GIVER", "ACCEPT"]


def test_idle_farms_when_mob_near_else_explores():
    assert plan_subgoals(_obs(mobs=1))[0]["subgoal"] == "FARM"
    assert plan_subgoals(_obs())[0]["subgoal"] == "EXPLORE"


def test_current_subgoal_returns_first_step():
    assert current_subgoal(_obs(ready=1, giver_dist=2.0))["skill"] == "turn_in_quest"


def test_death_uses_respawn_skill_not_heal():
    # воскрешение — отдельный навык с контрактом is_dead -> is_alive
    assert plan_subgoals(_obs(dead=True))[0]["skill"] == "respawn"


# ------------------------------------------------------------ Planner dwell

def test_planner_holds_subgoal_for_min_dwell():
    p = Planner(min_dwell=20)
    first = p.step(_obs(mobs=1))
    # состояние поменялось, но dwell не истёк -> цель та же
    for _ in range(5):
        held = p.step(_obs(quest_available=True))
    assert held["subgoal"] == first["subgoal"]


def test_planner_replans_after_dwell_expires():
    p = Planner(min_dwell=3)
    p.step(_obs(mobs=1))
    for _ in range(4):
        out = p.step(_obs(quest_available=True))
    assert out["subgoal"] == "ACCEPT"


def test_planner_force_replans_immediately():
    p = Planner(min_dwell=100)
    p.step(_obs(mobs=1))
    out = p.step(_obs(quest_available=True), force=True)
    assert out["subgoal"] == "ACCEPT"


def test_planner_urgent_death_ignores_dwell():
    p = Planner(min_dwell=100)
    p.step(_obs(mobs=1))
    out = p.step(_obs(dead=True))
    assert out["subgoal"] == "RESPAWN"


def test_planner_urgent_low_hp_ignores_dwell():
    p = Planner(min_dwell=100)
    p.step(_obs(mobs=1))
    assert p.step(_obs(hp=0.15))["subgoal"] == "SURVIVE"
    # нечем лечиться -> ждать реген, но всё равно НЕ квест
    assert p.step(_obs(hp=0.15, items={"rough_hide": 3}),
                  force=True)["subgoal"] == "REGEN"


def test_planner_advances_to_next_step_on_done():
    p = Planner(min_dwell=100)
    p.step(_obs(ready=1, giver_dist=40.0))     # [RETURN_TO_GIVER, TURN_IN]
    p.on_subgoal_done()
    assert p.current["subgoal"] == "TURN_IN"


def test_planner_reset_clears_state():
    p = Planner()
    p.step(_obs(mobs=1))
    p.reset()
    assert p.current is None and p.plan == []
