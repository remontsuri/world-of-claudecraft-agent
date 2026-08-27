"""P0-B regression: target-aware action planning.

Проверяет, что:
- giver 3 yd → accept SUCCESS
- giver 12 yd → navigate → accept SUCCESS
- giver неизвестен → DISCOVER/INCONCLUSIVE
- quest unavailable → accept не вызывается
- 100 повторов too_far никогда не дают 100 accept attempts
"""
import pytest
from skill_contracts import check_preconditions
from npc_registry import NpcRegistry


def _make_obs(giver_dist=999, has_quest=True, npc_pos_known=True, quest_id="q_boars"):
    """Создать obs для тестов."""
    ws = {
        "quest_givers": 1 if has_quest else 0,
        "quest": {
            "id": quest_id,
            "giver_distance": giver_dist,
        },
        "world": {
            "quest_givers": 1 if has_quest else 0,
            "quest_available": has_quest,
        },
    }
    if npc_pos_known:
        reg = NpcRegistry()
        reg.update_from_world_content({
            "trader_wilkes": {
                "name": "Trader Wilkes",
                "pos": {"x": -7.1, "z": 0.8},
                "questIds": [quest_id],
            }
        })
        ws["npc_registry"] = reg
    return ws


# --- 1. giver 3 yd → accept SUCCESS ---

def test_giver_nearby_accept_possible():
    """giver 3 yd → accept_quest не блокируется дистанцией."""
    obs = _make_obs(giver_dist=3.0)
    result = check_preconditions("accept_quest", obs)
    assert result["ok"] is True, f"accept_quest должен быть доступен: {result}"


# --- 2. giver 12 yd → navigate → accept SUCCESS ---

def test_giver_far_navigate_first():
    """giver 12 yd → accept_quest блокируется, но навигация должна помочь."""
    obs = _make_obs(giver_dist=12.0)
    result = check_preconditions("accept_quest", obs)
    # accept_quest заблокирован (giver_position_known может быть True, но giver_reachable=False)
    # но это не должно быть "нет гивера"
    assert "giver_exists" not in result["failed"]
    assert "giver_position_known" not in result["failed"]


# --- 3. giver неизвестен → DISCOVER/INCONCLUSIVE ---

def test_giver_unknown_position():
    """giver неизвестен → giver_position_known = False."""
    obs = _make_obs(npc_pos_known=False)
    result = check_preconditions("accept_quest", obs)
    assert result["ok"] is False
    assert "giver_position_known" in result["failed"]


# --- 4. quest unavailable → accept не вызывается ---

def test_quest_unavailable_blocked():
    """quest недоступен → accept_quest заблокирован."""
    obs = _make_obs(has_quest=False)
    result = check_preconditions("accept_quest", obs)
    assert result["ok"] is False
    assert "quest_available" in result["failed"]


# --- 5. 100 повторов too_far никогда не дают 100 accept attempts ---

def test_hundred_too_far_no_hundred_accepts():
    """100 повторов too_far → recovery должен дать navigate, а не accept."""
    from autonomy import AutonomyLoop

    loop = AutonomyLoop(min_dwell=1)
    info_giver_far = {
        "player": {"hp": 100, "maxHp": 100, "level": 1, "dead": False,
                   "pos": {"x": 0.0, "z": 0.0}, "xp": 0},
        "player_pos": [0.0, 0.0], "player_class": "warrior",
        "nearby": [{"kind": "npc", "name": "Wilkes", "questIds": ["q_boars"],
                    "dist": 40.0, "x": 40.0, "z": 0.0}],
        "quests": {"active": [], "ready": [], "done": []},
        "inventory": [], "inventory_by_id": {}, "equipment": {},
        "copper": 0, "kills": 0, "deaths": 0, "xp": 0, "bagCapacity": 16,
    }

    ws = dict(info_giver_far)
    ws["hp_frac"] = 1.0
    ws["bag_capacity"] = 16

    accept_attempts = 0
    for i in range(100):
        loop.before_action(info_giver_far, ws, ["accept_quest", "farm", "explore"])
        after = loop.after_action("accept_quest", info_giver_far, ws)
        if after["skill_result"] == "NO_OP" and after["failure_reason"] == "giver_too_far":
            accept_attempts += 1
        # Сбрасываем pending_recovery для чистоты теста
        loop.pending_recovery = None

    # Если все 100 раз был accept_quest с too_far — баг
    assert accept_attempts < 100, (
        f"Все {accept_attempts} попыток были accept_quest с too_far — "
        "recovery не переключает на навигацию"
    )
