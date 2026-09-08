"""STREAM J3 — Tests for memory-aware Planner.

Запуск: cd python && python -m pytest test_planner_memory.py -v

Acceptance criteria:
- [ ] Planner читает StrategyMemory перед генерацией плана
- [ ] При повторном планировании того же goal — альтернативный план
- [ ] Тест: после провала APPROACH, следующий план содержит альтернативу
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from planner import Planner, plan_subgoals, _goal_key
from strategy_memory import StrategyMemory
from memory import ExperienceStore


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


# ---- Test 1: Planner reads StrategyMemory before generating plan ----

def test_planner_reads_strategy_memory(tmp_path):
    """Planner должен читать StrategyMemory и учитывать proven strategies."""
    sm = StrategyMemory(path=str(tmp_path / "strat.json"))
    sm.record_completion("quest_obj:kill:forest_wolf", "farm")

    p = Planner(min_dwell=1, strat_mem=sm)
    obs = _obs(active=1, nxt={"type": "kill", "target_mob_id": "forest_wolf",
                              "remaining": 3}, mobs=1)
    result = p.step(obs)

    # Planner should have read StrategyMemory and annotated the plan
    assert hasattr(p, 'strat_mem')
    assert p.strat_mem is sm
    # The plan should be generated (not None)
    assert result is not None


def test_planner_uses_proven_strategy_hint(tmp_path):
    """Если StrategyMemory знает успешную стратегию — plan содержит hint."""
    sm = StrategyMemory(path=str(tmp_path / "strat.json"))
    sm.record_completion("quest_obj:kill:forest_wolf", "farm")

    p = Planner(min_dwell=1, strat_mem=sm)
    obs = _obs(active=1, nxt={"type": "kill", "target_mob_id": "forest_wolf",
                              "remaining": 3}, mobs=1)
    p.step(obs)

    # First step should have _proven_strategy annotation
    assert p.plan[0].get("_proven_strategy") == "farm"


# ---- Test 2: Alternative plan after APPROACH failure ----

def test_planner_alternative_after_approach_failure(tmp_path):
    """После провала APPROACH, следующий план содержит FIND_MOB (альтернатива)."""
    sm = StrategyMemory(path=str(tmp_path / "strat.json"))
    p = Planner(min_dwell=1, strat_mem=sm)

    # First plan: mob visible but out of range -> APPROACH
    obs1 = _obs(active=1, nxt={"type": "kill", "target_mob_id": "forest_wolf",
                               "remaining": 3}, mobs=1)
    obs1["mobs"] = [{"distance": 50.0, "id": "wolf_1"}]

    result1 = p.step(obs1)
    assert result1["subgoal"] == "APPROACH"

    # Simulate: APPROACH was tried and failed
    approach_step = {"subgoal": "APPROACH", "skill": "navigate",
                     "target": {"mob_id": "wolf_1"}}
    p.record_step_outcome(approach_step, "FAILURE", "mob_too_far")

    # Force replan — should inject alternative (FIND_MOB instead of APPROACH)
    p.force_replan()
    result2 = p.step(obs1)

    # After APPROACH failure, plan should contain FIND_MOB as alternative
    assert result2["subgoal"] == "FIND_MOB"
    assert result2.get("reason") == "approach_failed_alternative"


def test_planner_failed_steps_tracked(tmp_path):
    """Planner отслеживает failed steps per goal."""
    sm = StrategyMemory(path=str(tmp_path / "strat.json"))
    p = Planner(min_dwell=1, strat_mem=sm)

    obs = _obs(active=1, nxt={"type": "kill", "target_mob_id": "forest_wolf",
                              "remaining": 3}, mobs=1)
    p.step(obs)

    # Record failure
    p.record_step_outcome({"subgoal": "APPROACH"}, "FAILURE", "out_of_range")

    goal_key = p._current_goal_key
    assert goal_key in p._failed_steps
    assert "APPROACH" in p._failed_steps[goal_key]


# ---- Test 3: Lesson logging ----

def test_planner_logs_lessons(tmp_path):
    """Planner логирует planned_step -> result -> lesson."""
    sm = StrategyMemory(path=str(tmp_path / "strat.json"))
    p = Planner(min_dwell=1, strat_mem=sm)

    obs = _obs(active=1, nxt={"type": "kill", "target_mob_id": "forest_wolf",
                              "remaining": 3}, mobs=1)
    p.step(obs)

    p.record_step_outcome({"subgoal": "KILL"}, "SUCCESS", "")
    p.record_step_outcome({"subgoal": "LOOT"}, "FAILURE", "no_corpse")

    assert len(p.lessons) == 2
    assert p.lessons[0]["step"] == "KILL"
    assert p.lessons[0]["result"] == "SUCCESS"
    assert p.lessons[1]["step"] == "LOOT"
    assert p.lessons[1]["result"] == "FAILURE"
    assert p.lessons[1]["reason"] == "no_corpse"


# ---- Test 4: StrategyMemory integration ----

def test_planner_writes_to_strategy_memory(tmp_path):
    """Planner записывает step outcomes в StrategyMemory."""
    sm = StrategyMemory(path=str(tmp_path / "strat.json"))
    p = Planner(min_dwell=1, strat_mem=sm)

    obs = _obs(active=1, nxt={"type": "kill", "target_mob_id": "forest_wolf",
                              "remaining": 3}, mobs=1)
    p.step(obs)

    p.record_step_outcome({"subgoal": "KILL"}, "SUCCESS", "")

    goal_key = p._current_goal_key
    rec = sm.strategies.get(goal_key, {})
    assert rec.get("steps", {}).get("success", 0) >= 1


# ---- Test 5: No memory = safe fallback ----

def test_planner_without_memory_is_safe():
    """Planner без memory работает как раньше (backward compat)."""
    p = Planner(min_dwell=1)
    obs = _obs(active=1, nxt={"type": "kill", "target_mob_id": "forest_wolf",
                              "remaining": 3}, mobs=1)
    result = p.step(obs)
    assert result is not None
    assert "subgoal" in result


# ---- Test 6: goal_key stability ----

def test_goal_key_stable_for_same_quest():
    """goal_key стабилен для одного и того же quest objective."""
    obs = _obs(active=1, nxt={"type": "kill", "target_mob_id": "forest_wolf",
                              "remaining": 3})
    key1 = _goal_key(obs)
    key2 = _goal_key(obs)
    assert key1 == key2
    assert "kill" in key1
    assert "forest_wolf" in key1


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
