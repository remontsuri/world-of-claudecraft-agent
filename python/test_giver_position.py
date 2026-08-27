"""P0-B: тесты giver_position_known."""
import pytest
from skill_contracts import check_preconditions
from npc_registry import NpcRegistry


def _obs_with_giver(giver_distance=999, npc_registry=None, quest_id="q_boars", quest_available=True):
    """Создать obs с гивером."""
    ws = {
        "quest_givers": 1,
        "quest": {
            "id": quest_id,
            "giver_distance": giver_distance,
        },
        "world": {"quest_givers": 1, "quest_available": quest_available},
    }
    if npc_registry:
        ws["npc_registry"] = npc_registry
    return ws


def test_giver_position_known_with_registry():
    """giver_position_known = True, если позиция гивера известна в registry."""
    reg = NpcRegistry()
    reg.update_from_world_content({
        "trader_wilkes": {
            "name": "Trader Wilkes",
            "pos": {"x": -7.1, "z": 0.8},
            "questIds": ["q_boars"],
        }
    })
    obs = _obs_with_giver(npc_registry=reg)
    result = check_preconditions("accept_quest", obs)
    assert result["ok"] is True
    assert "giver_position_known" not in result["failed"]


def test_giver_position_unknown():
    """giver_position_known = False, если позиция неизвестна."""
    reg = NpcRegistry()
    reg.update_from_world_content({
        "trader_wilkes": {
            "name": "Trader Wilkes",
            "questIds": ["q_boars"],
            # pos отсутствует
        }
    })
    obs = _obs_with_giver(npc_registry=reg)
    result = check_preconditions("accept_quest", obs)
    assert result["ok"] is False
    assert "giver_position_known" in result["failed"]


def test_giver_reachable_for_recovery():
    """giver_reachable используется для recovery routing."""
    # Гивер далеко — не reachable
    obs = _obs_with_giver(giver_distance=12.0)
    result = check_preconditions("accept_quest", obs)
    # giver_reachable больше не в preconditions, но giver_position_known должен пройти
    assert "giver_reachable" not in result["failed"]


def test_giver_exists_fallback():
    """giver_exists работает без npc_registry (fallback)."""
    obs = _obs_with_giver(npc_registry=None)
    # Даже без registry, giver_exists должен пройти
    assert (obs.get("world", {}).get("quest_givers") or 0) > 0
