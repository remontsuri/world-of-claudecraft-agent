"""RED TESTS: facing / turn geometry.

Measured facts (skill world-of-claudecraft-cdp-verified):
  movement vector = (sin(facing), cos(facing)); facing=0 -> +Z.
  turnLeft INCREASES facing, turnRight DECREASES it.
  desired heading = atan2(dx, dz); off>0 -> turnLeft.
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))

from nav_policy import plan_leg


def _pos(x, z):
    return [x, z]


def test_no_turn_when_facing_target():
    """If already facing the target, plan_leg should NOT issue a turn."""
    player = _pos(0, 0)
    target = _pos(0, 10)   # straight ahead (+Z)
    facing = 0.0           # facing +Z
    plan = plan_leg(player, target, facing, arrive_dist=4.0)
    assert plan is not None
    assert plan["turns"] == 0, f"expected no turn, got {plan}"


def test_turn_left_when_target_at_plus_x():
    """Target at +X from facing +Z -> turnLeft (+1)."""
    player = _pos(0, 0)
    target = _pos(10, 0)   # +X
    facing = 0.0           # facing +Z
    plan = plan_leg(player, target, facing, arrive_dist=4.0)
    assert plan is not None
    assert plan["turns"] > 0, f"expected turnLeft (+1), got {plan}"


def test_turn_right_when_target_at_minus_x():
    """Target at -X from facing +Z -> turnRight (-1)."""
    player = _pos(0, 0)
    target = _pos(-10, 0)   # -X
    facing = 0.0            # facing +Z
    plan = plan_leg(player, target, facing, arrive_dist=4.0)
    assert plan is not None
    assert plan["turns"] < 0, f"expected turnRight (-1), got {plan}"


def test_arrived_returns_none():
    """When within arrive_dist, plan_leg returns None (no action needed)."""
    player = _pos(0, 0)
    target = _pos(0, 2)   # 2 yd away, arrive_dist=4
    facing = 0.0
    plan = plan_leg(player, target, facing, arrive_dist=4.0)
    assert plan is None, f"expected None (arrived), got {plan}"


def test_forward_ticks_positive_when_aligned():
    """When aligned, forward_ticks should be > 0."""
    player = _pos(0, 0)
    target = _pos(0, 20)   # straight ahead, 20 yd
    facing = 0.0
    plan = plan_leg(player, target, facing, arrive_dist=4.0)
    assert plan is not None
    assert plan["forward_ticks"] > 0, f"expected forward movement, got {plan}"


def test_turn_then_forward_sequence():
    """First call turns, subsequent call (after facing update) moves forward."""
    player = _pos(0, 0)
    target = _pos(10, 0)   # +X
    facing = 0.0           # facing +Z
    plan1 = plan_leg(player, target, facing, arrive_dist=4.0)
    assert plan1["turns"] > 0, "first leg should turn left"
    # Simulate turn completion: update facing toward target
    dx = target[0] - player[0]
    dz = target[1] - player[1]
    new_facing = math.atan2(dx, dz)  # now facing target
    plan2 = plan_leg(player, target, new_facing, arrive_dist=4.0)
    assert plan2["turns"] == 0, f"second leg should not turn, got {plan2}"
    assert plan2["forward_ticks"] > 0, f"second leg should move forward, got {plan2}"
