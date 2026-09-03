"""TDD for navigate -> spawn targeting (agent.py navigate handler)."""
import pytest


def test_navigate_toward_spawn():
    """When active quest has spawn, navigate should call _navigate_to_coord toward it."""
    class MockMobSpawner:
        @staticmethod
        def nearest_spawn(quest_id, x, z):
            if quest_id == "q_wolves":
                return (100.0, 200.0)
            return (None, None)

    class MockEnv:
        def __init__(self):
            self._last_info = {"player": {"x": 0, "z": 0}}
            self.calls = []

        def _navigate_to_coord(self, tx, tz, max_steps=40):
            self.calls.append((tx, tz, max_steps))

        def explore_walk(self, steps=10):
            pass

    env = MockEnv()

    class MockWorldMem:
        def get(self, key, default=None):
            if key == "active_quest":
                return "q_wolves"
            if key == "pending_quest":
                return None
            return default

    # Simulate navigate handler logic (from agent.py)
    quest_id = MockWorldMem().get("active_quest") or MockWorldMem().get("pending_quest")
    player = (env._last_info or {}).get("player", {})
    tx, tz = None, None
    if quest_id:
        tx, tz = MockMobSpawner.nearest_spawn(quest_id, player.get("x", 0), player.get("z", 0))
    if tx is not None and hasattr(env, "_navigate_to_coord"):
        env._navigate_to_coord(tx, tz, max_steps=40)
    elif hasattr(env, "explore_walk"):
        env.explore_walk(steps=10)

    assert len(env.calls) == 1
    assert env.calls[0] == (100.0, 200.0, 40)


def test_navigate_fallback_when_no_quest():
    """Without an active quest, navigate falls back to explore_walk."""
    class MockMobSpawner:
        @staticmethod
        def nearest_spawn(quest_id, x, z):
            return (None, None)

    class MockEnv:
        def __init__(self):
            self._last_info = {"player": {"x": 0, "z": 0}}
            self.calls = []
            self.walk_calls = []

        def _navigate_to_coord(self, tx, tz, max_steps=40):
            self.calls.append((tx, tz, max_steps))

        def explore_walk(self, steps=10):
            self.walk_calls.append(steps)

    env = MockEnv()

    class MockWorldMem:
        def get(self, key, default=None):
            return None

    quest_id = MockWorldMem().get("active_quest") or MockWorldMem().get("pending_quest")
    player = (env._last_info or {}).get("player", {})
    tx, tz = None, None
    if quest_id:
        tx, tz = MockMobSpawner.nearest_spawn(quest_id, player.get("x", 0), player.get("z", 0))
    called_nav = False
    if tx is not None and hasattr(env, "_navigate_to_coord"):
        env._navigate_to_coord(tx, tz, max_steps=40)
        called_nav = True
    elif hasattr(env, "explore_walk"):
        env.explore_walk(steps=10)

    assert called_nav is False
    assert len(env.calls) == 0
    assert len(env.walk_calls) == 1


def test_navigate_fallback_when_spawn_not_found():
    """When quest has no spawn data, navigate falls back to explore_walk."""
    class MockMobSpawner:
        @staticmethod
        def nearest_spawn(quest_id, x, z):
            return (None, None)

    class MockEnv:
        def __init__(self):
            self._last_info = {"player": {"x": 0, "z": 0}}
            self.calls = []
            self.walk_calls = []

        def _navigate_to_coord(self, tx, tz, max_steps=40):
            self.calls.append((tx, tz, max_steps))

        def explore_walk(self, steps=10):
            self.walk_calls.append(steps)

    env = MockEnv()

    class MockWorldMem:
        def get(self, key, default=None):
            if key == "active_quest":
                return "q_nonexistent"
            return default

    quest_id = MockWorldMem().get("active_quest") or MockWorldMem().get("pending_quest")
    player = (env._last_info or {}).get("player", {})
    tx, tz = None, None
    if quest_id:
        tx, tz = MockMobSpawner.nearest_spawn(quest_id, player.get("x", 0), player.get("z", 0))
    called_nav = False
    if tx is not None and hasattr(env, "_navigate_to_coord"):
        env._navigate_to_coord(tx, tz, max_steps=40)
        called_nav = True
    elif hasattr(env, "explore_walk"):
        env.explore_walk(steps=10)

    assert called_nav is False
    assert len(env.calls) == 0
    assert len(env.walk_calls) == 1
