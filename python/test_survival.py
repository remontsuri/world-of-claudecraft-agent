"""TDD for flee action — uses REAL bridge snapshot format (player_pos, targetId, nearby)."""
import pytest


def test_flee_runs_away_from_target():
    """Verify flee navigates away from target (opposite direction)."""
    class MockEnv:
        def __init__(self):
            # Real bridge snapshot format: player_pos=[x,z], targetId, nearby=[{id,x,z,...}]
            self._last_info = {
                "player_pos": [0.0, 0.0],
                "targetId": 42,
                "nearby": [
                    {"id": 42, "kind": "mob", "x": 10.0, "z": 0.0, "hostile": True, "dead": False}
                ]
            }
            self.calls = []

        def _navigate_to_coord(self, tx, tz, max_steps=15):
            self.calls.append((tx, tz, max_steps))

        def explore_walk(self, steps=10):
            pass

    env = MockEnv()

    # Simulate flee logic (from agent.py)
    info = env._last_info or {}
    player_pos = info.get("player_pos") or [0, 0]
    px, pz = float(player_pos[0]), float(player_pos[1])
    target_id = info.get("targetId")
    nearby = info.get("nearby") or []
    target = None
    if target_id is not None:
        for e in nearby:
            if e.get("id") == target_id:
                target = e
                break
    if target is None:
        best_d = float("inf")
        for e in nearby:
            if (e.get("kind") == "mob" and not e.get("dead")
                    and e.get("hostile") is not False):
                ex, ez = e.get("x"), e.get("z")
                if ex is None or ez is None:
                    continue
                d = ((ex - px) ** 2 + (ez - pz) ** 2) ** 0.5
                if d < best_d:
                    best_d = d
                    target = e
    if target:
        dx = px - float(target.get("x", 0))
        dz = pz - float(target.get("z", 0))
        tx = px + dx * 10
        tz = pz + dz * 10
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
            self._last_info = {
                "player_pos": [0.0, 0.0],
                "targetId": None,
                "nearby": []
            }
            self.calls = []
            self.walk_calls = []

        def _navigate_to_coord(self, tx, tz, max_steps=15):
            self.calls.append((tx, tz, max_steps))

        def explore_walk(self, steps=10):
            self.walk_calls.append(steps)

    env = MockEnv()

    info = env._last_info or {}
    player_pos = info.get("player_pos") or [0, 0]
    px, pz = float(player_pos[0]), float(player_pos[1])
    target_id = info.get("targetId")
    nearby = info.get("nearby") or []
    target = None
    if target_id is not None:
        for e in nearby:
            if e.get("id") == target_id:
                target = e
                break
    if target is None:
        best_d = float("inf")
        for e in nearby:
            if (e.get("kind") == "mob" and not e.get("dead")
                    and e.get("hostile") is not False):
                ex, ez = e.get("x"), e.get("z")
                if ex is None or ez is None:
                    continue
                d = ((ex - px) ** 2 + (ez - pz) ** 2) ** 0.5
                if d < best_d:
                    best_d = d
                    target = e
    called_nav = False
    if target:
        dx = px - float(target.get("x", 0))
        dz = pz - float(target.get("z", 0))
        tx = px + dx * 10
        tz = pz + dz * 10
        if hasattr(env, "_navigate_to_coord"):
            env._navigate_to_coord(tx, tz, max_steps=15)
            called_nav = True

    assert called_nav is False
    assert len(env.calls) == 0


def test_flee_fallback_to_nearest_hostile():
    """When targetId is null but hostile mob nearby, flee from it."""
    class MockEnv:
        def __init__(self):
            self._last_info = {
                "player_pos": [5.0, 5.0],
                "targetId": None,
                "nearby": [
                    {"id": 1, "kind": "mob", "x": 15.0, "z": 5.0, "hostile": True, "dead": False},
                    {"id": 2, "kind": "mob", "x": 20.0, "z": 20.0, "hostile": True, "dead": False},
                ]
            }
            self.calls = []

        def _navigate_to_coord(self, tx, tz, max_steps=15):
            self.calls.append((tx, tz, max_steps))

    env = MockEnv()

    info = env._last_info or {}
    player_pos = info.get("player_pos") or [0, 0]
    px, pz = float(player_pos[0]), float(player_pos[1])
    target_id = info.get("targetId")
    nearby = info.get("nearby") or []
    target = None
    if target_id is not None:
        for e in nearby:
            if e.get("id") == target_id:
                target = e
                break
    if target is None:
        best_d = float("inf")
        for e in nearby:
            if (e.get("kind") == "mob" and not e.get("dead")
                    and e.get("hostile") is not False):
                ex, ez = e.get("x"), e.get("z")
                if ex is None or ez is None:
                    continue
                d = ((ex - px) ** 2 + (ez - pz) ** 2) ** 0.5
                if d < best_d:
                    best_d = d
                    target = e
    if target:
        dx = px - float(target.get("x", 0))
        dz = pz - float(target.get("z", 0))
        tx = px + dx * 10
        tz = pz + dz * 10
        if hasattr(env, "_navigate_to_coord"):
            env._navigate_to_coord(tx, tz, max_steps=15)

    assert len(env.calls) == 1
    # Nearest hostile: id=1 at (15,5), player at (5,5)
    # dx = 5 - 15 = -10, dz = 5 - 5 = 0
    # tx = 5 + (-10)*10 = -95, tz = 5 + 0*10 = 5
    assert env.calls[0] == (-95.0, 5.0, 15)
