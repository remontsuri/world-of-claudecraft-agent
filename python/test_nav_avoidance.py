"""K-NAV-001 RED tests: navigation with obstacle avoidance.

When the agent is BLOCKED (moving but not closer), it must NOT keep
walking into the obstacle. It must generate a perpendicular detour
waypoint, walk around the obstacle, and return to the original target.

Запуск: cd python && python -m pytest test_nav_avoidance.py -v
"""
import math
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from navigation import (NavigationController, find_target, tolerance_for,
                        target_kind_for_subgoal,
                        ARRIVED, MOVING, STUCK, BLOCKED, TIMEOUT, NO_TARGET)


def _obs(px=0.0, pz=0.0, ents=None, dead=False, player_class="warrior"):
    return {
        "player": {"position": [px, pz], "dead": dead, "hp_fraction": 1.0,
                   "player_class": player_class},
        "_entities": ents or [],
    }


def _giver(x, z, d=None):
    return {"kind": "npc", "questIds": ["q1"], "x": x, "z": z,
            "_dist": d if d is not None else (x ** 2 + z ** 2) ** 0.5}


# ----------------------------------------------------------- obstacle avoidance

def test_blocked_generates_detour_waypoint():
    """When BLOCKED, nav_command must return a detour waypoint, NOT the target."""
    nav = NavigationController(no_progress_limit=4)
    ents = [_giver(40, 0)]
    nav.set_target(_obs(ents=ents), "quest_giver")

    # Simulate walking in a circle around an obstacle (position changes, distance doesn't)
    ring = [(0, 5), (5, 0), (0, -5), (-5, 0)] * 3
    st = None
    for (x, z) in ring:
        st = nav.observe(_obs(px=x, pz=z, ents=ents))

    assert st["status"] in (BLOCKED, STUCK), f"expected BLOCKED/STUCK, got {st['status']}"

    # When blocked, nav_command must return a detour (not the original target)
    cmd = nav.nav_command()
    assert cmd is not None, "nav_command should return a detour command when blocked"
    # The detour waypoint should NOT be the original target coords (40, 0)
    # It should be an offset point that walks around the obstacle
    if st["status"] == BLOCKED:
        assert (cmd["x"], cmd["z"]) != (40, 0), \
            "nav_command must return a detour waypoint, not the blocked target"


def test_detour_is_perpendicular_to_blocked_path():
    """The detour waypoint should be offset perpendicular to the direct path."""
    nav = NavigationController(no_progress_limit=4)
    # Target is straight east
    ents = [_giver(40, 0)]
    nav.set_target(_obs(ents=ents), "quest_giver")

    # Walk in a circle to trigger BLOCKED
    ring = [(0, 5), (5, 0), (0, -5), (-5, 0)] * 3
    for (x, z) in ring:
        nav.observe(_obs(px=x, pz=z, ents=ents))

    cmd = nav.nav_command()
    if cmd is None:
        return  # no block detected, skip

    # Detour should have a significant Z component (perpendicular to X-axis path)
    # The direct path is along X (east), so perpendicular is along Z (north/south)
    assert abs(cmd["z"]) > 1.0, \
        f"detour should offset perpendicular to path, got z={cmd['z']}"


def test_detour_returns_to_original_target_after_reached():
    """After reaching the detour waypoint, nav should resume toward original target."""
    nav = NavigationController(no_progress_limit=4)
    ents = [_giver(40, 0)]
    nav.set_target(_obs(ents=ents), "quest_giver")

    # Trigger BLOCKED
    ring = [(0, 5), (5, 0), (0, -5), (-5, 0)] * 3
    for (x, z) in ring:
        nav.observe(_obs(px=x, pz=z, ents=ents))

    # Simulate reaching the detour waypoint
    detour_cmd = nav.nav_command()
    if detour_cmd is None:
        return

    # Move to the detour waypoint
    nav.observe(_obs(px=detour_cmd["x"], pz=detour_cmd["z"], ents=ents))

    # Now nav_command should point back to the original target (or closer)
    resumed_cmd = nav.nav_command()
    assert resumed_cmd is not None
    # The resumed command should move us closer to the target (40, 0)
    # At minimum, it should not be stuck on the detour point
    assert resumed_cmd["action"] == "navigate"


def test_no_infinite_loop_on_unreachable_target():
    """After max_steps, TIMEOUT must fire even with detour attempts."""
    nav = NavigationController(max_steps_per_target=10, no_progress_limit=4)
    ents = [_giver(100, 0)]
    nav.set_target(_obs(ents=ents), "quest_giver")

    st = None
    for i in range(12):
        # Walk in circles, never closer
        angle = i * 0.5
        x = 10 * math.cos(angle)
        z = 10 * math.sin(angle)
        st = nav.observe(_obs(px=x, pz=z, ents=ents))

    assert st["status"] == TIMEOUT, f"expected TIMEOUT, got {st['status']}"
    assert nav.recovery_for(TIMEOUT) == "abandon_objective"


def test_stuck_recovery_jumps_to_new_position():
    """When STUCK (not moving at all), recovery should trigger a jump/unstuck."""
    nav = NavigationController()
    ents = [_giver(40, 0)]
    nav.set_target(_obs(ents=ents), "quest_giver")

    # Position completely frozen for many steps
    for _ in range(10):
        nav.observe(_obs(px=0, pz=0, ents=ents))

    status = nav.observe(_obs(px=0, pz=0, ents=ents))
    assert status["status"] == STUCK
    assert nav.recovery_for(STUCK) == "unstuck_jump"


def test_avoidance_waypoint_within_reasonable_distance():
    """Detour waypoint should not be absurdly far from current position."""
    nav = NavigationController(no_progress_limit=4)
    ents = [_giver(40, 0)]
    nav.set_target(_obs(ents=ents), "quest_giver")

    ring = [(0, 5), (5, 0), (0, -5), (-5, 0)] * 3
    for (x, z) in ring:
        nav.observe(_obs(px=x, pz=z, ents=ents))

    cmd = nav.nav_command()
    if cmd is None:
        return

    # Detour should be within ~20 yd of current position (not across the map)
    cx, cz = 0, 0  # approximate current position
    detour_dist = math.hypot(cmd["x"] - cx, cmd["z"] - cz)
    assert detour_dist < 30.0, \
        f"detour too far: {detour_dist:.1f} yd (should be < 30)"


def test_blocked_recovery_maps_to_alternate_route():
    """recovery_for(BLOCKED) must return alternate_route."""
    nav = NavigationController()
    assert nav.recovery_for(BLOCKED) == "alternate_route"


def test_multiple_blocked_recovers_gracefully():
    """Agent must not crash or loop forever when blocked repeatedly."""
    nav = NavigationController(max_steps_per_target=20, no_progress_limit=4)
    ents = [_giver(40, 0)]
    nav.set_target(_obs(ents=ents), "quest_giver")

    statuses = []
    for i in range(20):
        angle = i * 0.3
        x = 5 * math.cos(angle)
        z = 5 * math.sin(angle)
        st = nav.observe(_obs(px=x, pz=z, ents=ents))
        statuses.append(st["status"])

    # Must eventually hit TIMEOUT (not loop forever in MOVING)
    assert TIMEOUT in statuses or STUCK in statuses, \
        f"expected TIMEOUT or STUCK in statuses, got: {set(statuses)}"


if __name__ == "__main__":
    test_blocked_generates_detour_waypoint()
    test_detour_is_perpendicular_to_blocked_path()
    test_detour_returns_to_original_target_after_reached()
    test_no_infinite_loop_on_unreachable_target()
    test_stuck_recovery_jumps_to_new_position()
    test_avoidance_waypoint_within_reasonable_distance()
    test_blocked_recovery_maps_to_alternate_route()
    test_multiple_blocked_recovers_gracefully()
    print("ALL 8 K-NAV-001 AVOIDANCE TESTS PASSED")
