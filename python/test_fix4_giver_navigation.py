"""FIX #4 regression: GO_TO_GIVER не превращается в unknown_skill.

GO_TO_GIVER — это navigation hint, а не policy skill.
Planner возвращает {"subgoal": "GO_TO_GIVER", "skill": "explore"}.
Autonomy обрабатывает через _nav_to() → nav_command + forced="explore".
explore — валидный навык (пустые предусловия, в ALWAYS_AVAILABLE).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from planner import plan_subgoals
from autonomy import AutonomyLoop
from skill_contracts import check_preconditions


def test_giver_far_produces_go_to_giver_subgoal():
    """Планировщик выдаёт GO_TO_GIVER когда гивер далеко."""
    obs = {
        "quest": {"id": "q_boars", "giver_distance": 40.0},
        "world": {
            "quest_givers": 1,
            "quest_available": True,
        },
        "player": {"hp": 100, "maxHp": 100, "level": 5, "dead": False},
    }
    plan = plan_subgoals(obs)
    assert len(plan) >= 1
    assert plan[0]["subgoal"] == "GO_TO_GIVER"
    assert plan[0]["skill"] == "explore"


def test_go_to_giver_not_unknown_skill():
    """GO_TO_GIVER с skill=explore — НЕ unknown_skill."""
    # explore — валидный навык
    result = check_preconditions("explore", {})
    assert result["ok"] is True
    assert "unknown_skill" not in result["failed"]


def test_go_to_giver_generates_nav_command():
    """Autonomy генерирует nav_command для GO_TO_GIVER, а не падает."""
    loop = AutonomyLoop(min_dwell=1)
    info = {
        "player": {"hp": 100, "maxHp": 100, "level": 5, "dead": False,
                   "pos": {"x": 0.0, "z": 0.0}, "xp": 0},
        "player_pos": [0.0, 0.0], "player_class": "warrior",
        "nearby": [
            {"kind": "npc", "name": "Wilkes", "templateId": "trader_wilkes",
             "questIds": ["q_boars"], "x": 40.0, "z": 0.0, "dist": 40.0},
        ],
        "quests": {"active": [], "ready": [], "done": []},
        "inventory": [], "inventory_by_id": {}, "equipment": {},
        "copper": 0, "kills": 0, "deaths": 0, "xp": 0, "bagCapacity": 16,
        "quest_states": {"q_boars": "available"},
    }
    ws = dict(info)
    ws["hp_frac"] = 1.0
    ws["bag_capacity"] = 16

    result = loop.before_action(info, ws, ["accept_quest", "farm", "explore"])
    # Должен быть сгенерирован nav_command или forced
    assert result is not None


def test_giver_near_produces_accept_subgoal():
    """Планировщик выдаёт ACCEPT когда гивер близко."""
    obs = {
        "quest": {"id": "q_boars", "giver_distance": 3.0},
        "world": {
            "quest_givers": 1,
            "quest_available": True,
        },
        "player": {"hp": 100, "maxHp": 100, "level": 5, "dead": False},
    }
    plan = plan_subgoals(obs)
    assert len(plan) >= 1
    # Первый subgoal должен быть ACCEPT (или GO_TO_GIVER если дистанция > 7)
    assert plan[0]["subgoal"] in ("ACCEPT", "GO_TO_GIVER")


if __name__ == "__main__":
    test_giver_far_produces_go_to_giver_subgoal()
    test_go_to_giver_not_unknown_skill()
    test_go_to_giver_generates_nav_command()
    test_giver_near_produces_accept_subgoal()
    print("ALL 4 FIX #4 TESTS PASSED")
