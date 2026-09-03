"""TDD for MobSpawner — quest mob spawn areas from game source."""
import pytest
from pathlib import Path

EXPORT_PATH = Path(__file__).parent / "game_agent_export.json"


def test_export_exists():
    assert EXPORT_PATH.exists(), f"game_agent_export.json not found at {EXPORT_PATH}"


def test_load_spawns_returns_dict():
    from mob_spawner import load_spawns
    spawns = load_spawns()
    assert isinstance(spawns, dict)


def test_load_spawns_has_wolves():
    from mob_spawner import load_spawns
    spawns = load_spawns()
    assert "q_wolves" in spawns, f"q_wolves not found. Keys: {list(spawns.keys())[:10]}"
    assert len(spawns["q_wolves"]) > 0, "No spawn zones for q_wolves"


def test_wolves_spawn_has_coords():
    from mob_spawner import load_spawns
    spawns = load_spawns()
    wolf_spawns = spawns.get("q_wolves", [])
    if wolf_spawns:
        s = wolf_spawns[0]
        assert "x" in s and "z" in s, f"Missing x/z in spawn: {s}"
        assert "radius" in s, f"Missing radius in spawn: {s}"


def test_nearest_spawn_returns_coords():
    from mob_spawner import nearest_spawn
    x, z = nearest_spawn("q_wolves", 0, 0)
    assert x is not None and z is not None


def test_nearest_spawn_picks_closest():
    from mob_spawner import nearest_spawns
    spawns = nearest_spawns("q_wolves", 0, 0)
    assert len(spawns) > 0
    # First should be closest to origin
    first = spawns[0]
    assert "distance" in first
    distances = [s["distance"] for s in spawns]
    assert distances == sorted(distances), "Spawns not sorted by distance"


def test_nearest_spawn_unknown_quest():
    from mob_spawner import nearest_spawn
    x, z = nearest_spawn("q_nonexistent", 0, 0)
    assert x is None and z is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
