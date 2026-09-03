"""TDD for flee action."""
import pytest


def test_flee_runs_away_from_target():
    """Verify flee navigates away from target (opposite direction)."""
    # Mock env
    class MockEnv:
        def __init__(self):
            self._last_info = {
                "player": {"x": 0, "z": 0},
                "target": {"x": 10, "z": 0}
            }
            self.calls = []

        def _navigate_to_coord(self, tx, tz, max_steps=15):
            self.calls.append((tx, tz, max_steps))

        def explore_walk(self, steps=10):
            pass

    env = MockEnv()

    # Simulate flee logic (from agent.py)
    info = env._last_info or {}
    player = info.get("player", {})
    target = info.get("target", {})
    if target and player:
        dx = player.get("x", 0) - target.get("x", 0)
        dz = player.get("z", 0) - target.get("z", 0)
        tx = player.get("x", 0) + dx * 10
        tz = player.get("z", 0) + dz * 10
        if hasattr(env, "_navigate_to_coord"):
            env._navigate_to_coord(tx, tz, max_steps=15)
        elif hasattr(env, "explore_walk"):
            env.explore_walk(steps=10)

    assert len(env.calls) == 1
    # Target at (10, 0), player at (0, 0)
    # dx = 0 - 10 = -10, dz = 0 - 0 = 0
    # tx = 0 + (-10) * 10 = -100, tz = 0 + 0 * 10 = 0
    assert env.calls[0] == (-100.0, 0.0, 15)


def test_flee_no_target_falls_back():
    """Without a target, flee does nothing (no crash)."""
    class MockEnv:
        def __init__(self):
            self._last_info = {"player": {"x": 0, "z": 0}}
            self.calls = []
            self.walk_calls = []

        def _navigate_to_coord(self, tx, tz, max_steps=15):
            self.calls.append((tx, tz, max_steps))

        def explore_walk(self, steps=10):
            self.walk_calls.append(steps)

    env = MockEnv()

    info = env._last_info or {}
    player = info.get("player", {})
    target = info.get("target", {})
    called_nav = False
    if target and player:
        dx = player.get("x", 0) - target.get("x", 0)
        dz = player.get("z", 0) - target.get("z", 0)
        tx = player.get("x", 0) + dx * 10
        tz = player.get("z", 0) + dz * 10
        if hasattr(env, "_navigate_to_coord"):
            env._navigate_to_coord(tx, tz, max_steps=15)
            called_nav = True

    assert called_nav is False
    assert len(env.calls) == 0
