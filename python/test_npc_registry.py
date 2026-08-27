"""P0-A: тесты Canonical NPC Registry (FIX #2 + FIX #3)."""
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
    """Runtime entity имеет приоритет над worldContent (FIX #2)."""
    reg = NpcRegistry()
    reg.update_from_world_content({
        "trader_wilkes": {
            "name": "Trader Wilkes",
            "pos": {"x": -7.1, "z": 0.8},
        }
    })
    # Runtime entity с другой позицией — высший приоритет
    reg.update_from_runtime_entities([
        {"id": 12345, "templateId": "trader_wilkes", "pos": {"x": 10.0, "z": 20.0}}
    ])
    npc = reg.get("trader_wilkes")
    assert npc["x"] == 10.0  # runtime priority
    assert npc["z"] == 20.0
    assert npc["source"] == "runtime_entity"
    # FIX #3: entity_id сохранён отдельно
    assert npc["entity_id"] == 12345


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
    assert giver["npc_id"] == "trader_wilkes"  # FIX #3: npc_id, не id

    giver2 = reg.find_giver_for_quest("q_bandits")
    assert giver2 is not None
    assert giver2["npc_id"] == "marshal_redbrook"


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
    """WorldMemory как fallback для позиции (только если нет лучшего источника)."""
    reg = NpcRegistry()
    # NPC без позиции в worldContent
    reg.update_from_world_content({
        "trader_wilkes": {
            "name": "Trader Wilkes",
            "questIds": ["q_boars"],
        }
    })
    # Memory дает позицию — memory priority 0, но позиции нет → обновляется
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
    assert npc["source"] == "memory"


def test_npc_registry_reset():
    """Сброс реестра."""
    reg = NpcRegistry()
    reg.update_from_world_content({
        "npc1": {"name": "NPC1", "pos": {"x": 0, "z": 0}}
    })
    assert len(reg.all()) == 1
    reg.reset()
    assert len(reg.all()) == 0


# --- FIX #2 regression: source priority contract ---

def test_snapshot_does_not_override_runtime():
    """Snapshot (priority 1) НЕ должен перезаписывать runtime_entity (priority 3)."""
    reg = NpcRegistry()
    reg.update_from_runtime_entities([
        {"id": 1, "templateId": "npc_a", "pos": {"x": 10.0, "z": 10.0}}
    ])
    reg.update_from_snapshot([
        {"id": 1, "templateId": "npc_a", "kind": "npc", "x": 50.0, "z": 50.0}
    ])
    npc = reg.get("npc_a")
    assert npc["x"] == 10.0  # runtime сохранился
    assert npc["z"] == 10.0
    assert npc["source"] == "runtime_entity"


def test_world_content_overrides_snapshot():
    """world_content (priority 2) перезаписывает snapshot (priority 1)."""
    reg = NpcRegistry()
    reg.update_from_snapshot([
        {"id": 1, "templateId": "npc_a", "kind": "npc", "x": 50.0, "z": 50.0}
    ])
    reg.update_from_world_content({
        "npc_a": {"pos": {"x": 10.0, "z": 10.0}}
    })
    npc = reg.get("npc_a")
    assert npc["x"] == 10.0
    assert npc["z"] == 10.0
    assert npc["source"] == "world_content"


def test_memory_does_not_override_runtime():
    """Memory (priority 0) НЕ должен перезаписывать runtime_entity (priority 3)."""
    reg = NpcRegistry()
    reg.update_from_runtime_entities([
        {"id": 1, "templateId": "npc_a", "pos": {"x": 10.0, "z": 10.0}}
    ])
    class FakeMemory:
        givers = {
            "q_test": {"giver_id": "npc_a", "giver_pos": {"x": 100.0, "z": 200.0}}
        }
    reg.update_from_memory(FakeMemory())
    npc = reg.get("npc_a")
    assert npc["x"] == 10.0  # runtime сохранился
    assert npc["z"] == 10.0


# --- FIX #3 regression: canonical key contract ---

def test_runtime_entity_uses_template_id_as_key():
    """FIX #3: runtime entity использует templateId как ключ, НЕ entity.id."""
    reg = NpcRegistry()
    reg.update_from_runtime_entities([
        {"id": 99999, "templateId": "trader_wilkes", "pos": {"x": 5.0, "z": 5.0}}
    ])
    # Ключ = templateId, не entity.id
    assert "trader_wilkes" in reg.all()
    assert 99999 not in reg.all()
    npc = reg.get("trader_wilkes")
    assert npc is not None
    assert npc["entity_id"] == 99999  # entity_id сохранён отдельно
    assert npc["template_id"] == "trader_wilkes"


def test_snapshot_uses_template_id_as_key():
    """FIX #3: snapshot использует templateId как ключ, НЕ entity.id."""
    reg = NpcRegistry()
    reg.update_from_snapshot([
        {"id": 88888, "templateId": "marshal_redbrook", "kind": "npc", "x": 1.0, "z": 2.0}
    ])
    assert "marshal_redbrook" in reg.all()
    assert 88888 not in reg.all()
    npc = reg.get("marshal_redbrook")
    assert npc["entity_id"] == 88888
