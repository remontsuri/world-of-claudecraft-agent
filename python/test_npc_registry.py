"""P0-A: тесты Canonical NPC Registry."""
import pytest
from npc_registry import NpcRegistry


def test_npc_registry_world_content():
    """NPC из worldContent регистрируется в реестре."""
    reg = NpcRegistry()
    reg.update_from_world_content({
        "trader_wilkes": {
            "name": "Trader Wilkes",
            "pos": {"x": -7.1, "z": 0.8},
            "questIds": ["q_boars", "q_supplies"],
            "vendorItems": ["baked_bread"],
        }
    })
    npc = reg.get("trader_wilkes")
    assert npc is not None
    assert npc["name"] == "Trader Wilkes"
    assert npc["x"] == -7.1
    assert npc["z"] == 0.8
    assert "q_boars" in npc["quest_ids"]


def test_npc_registry_runtime_priority():
    """Runtime entity имеет приоритет над worldContent."""
    reg = NpcRegistry()
    reg.update_from_world_content({
        "trader_wilkes": {
            "name": "Trader Wilkes",
            "pos": {"x": -7.1, "z": 0.8},
        }
    })
    # Runtime entity с другой позицией
    reg.update_from_snapshot([
        {"id": "trader_wilkes", "kind": "npc", "x": 10.0, "z": 20.0}
    ])
    npc = reg.get("trader_wilkes")
    assert npc["x"] == 10.0  # runtime priority
    assert npc["z"] == 20.0


def test_npc_registry_find_giver():
    """Поиск гивера по quest_id."""
    reg = NpcRegistry()
    reg.update_from_world_content({
        "trader_wilkes": {
            "name": "Trader Wilkes",
            "pos": {"x": -7.1, "z": 0.8},
            "questIds": ["q_boars", "q_supplies"],
        },
        "marshal_redbrook": {
            "name": "Marshal Redbrook",
            "pos": {"x": 4.5, "z": 5.5},
            "questIds": ["q_bandits"],
        }
    })
    giver = reg.find_giver_for_quest("q_boars")
    assert giver is not None
    assert giver["id"] == "trader_wilkes"

    giver2 = reg.find_giver_for_quest("q_bandits")
    assert giver2 is not None
    assert giver2["id"] == "marshal_redbrook"


def test_npc_registry_unknown_position():
    """NPC с неизвестной позицией ≠ NPC absent."""
    reg = NpcRegistry()
    reg.update_from_world_content({
        "mystery_npc": {
            "name": "Mystery NPC",
            "questIds": ["q_mystery"],
            # pos отсутствует
        }
    })
    npc = reg.get("mystery_npc")
    assert npc is not None  # NPC существует
    assert npc.get("x") is None  # но позиция неизвестна
    assert npc.get("z") is None


def test_npc_registry_get_position():
    """Получение позиции гивера для квеста."""
    reg = NpcRegistry()
    reg.update_from_world_content({
        "trader_wilkes": {
            "name": "Trader Wilkes",
            "pos": {"x": -7.1, "z": 0.8},
            "questIds": ["q_boars"],
        }
    })
    pos = reg.get_giver_position_for_quest("q_boars")
    assert pos is not None
    assert pos["x"] == -7.1
    assert pos["z"] == 0.8

    # Неизвестный квест
    pos2 = reg.get_giver_position_for_quest("q_unknown")
    assert pos2 is None


def test_npc_registry_memory_fallback():
    """WorldMemory как fallback для позиции."""
    reg = NpcRegistry()
    # NPC без позиции в worldContent
    reg.update_from_world_content({
        "trader_wilkes": {
            "name": "Trader Wilkes",
            "questIds": ["q_boars"],
        }
    })
    # Memory дает позицию
    class FakeMemory:
        givers = {
            "q_boars": {
                "giver_id": "trader_wilkes",
                "giver_pos": {"x": 100.0, "z": 200.0},
            }
        }
    reg.update_from_memory(FakeMemory())
    npc = reg.get("trader_wilkes")
    assert npc["x"] == 100.0
    assert npc["z"] == 200.0


def test_npc_registry_reset():
    """Сброс реестра."""
    reg = NpcRegistry()
    reg.update_from_world_content({
        "npc1": {"name": "NPC1", "pos": {"x": 0, "z": 0}}
    })
    assert len(reg.all()) == 1
    reg.reset()
    assert len(reg.all()) == 0
