"""Geometric walker over bridge raw_move — the honest replacement for
navigateToCoord's scripted walk when we need multi-step approach with
fence-jump support (Fix6).

Measured geometry (skill world-of-claudecraft-cdp-verified,
references/local_bridge_nav_geometry.md):
  movement vector = (sin(facing), cos(facing)); facing=0 -> +Z.
  turnLeft INCREASES facing, turnRight DECREASES it.
  desired heading = atan2(dx, dz); off>0 -> turnLeft.

One call = one leg: turn toward target until |off|<=0.2, then forward N ticks,
with a jump pulse when a fence is suspected (stuck detection upstream).
"""
import math


def plan_leg(player_pos, target_pos, facing, max_ticks=8, arrive_dist=4.0):
    """Return {'turns': int(-1|0|1), 'forward_ticks': int, 'jump': bool}
    or None if arrived. turns: +1 = turnLeft, -1 = turnRight."""
    dx = target_pos[0] - player_pos[0]
    dz = target_pos[1] - player_pos[1]
    dist = math.hypot(dx, dz)
    if dist < arrive_dist:
        return None
    desired = math.atan2(dx, dz)
    off = ((desired - facing + math.pi) % (2 * math.pi)) - math.pi
    # each raw_move tick rotates ~0.55 rad with forward; pure turn ~0.6 rad/tick
    if abs(off) > 0.25:
        direction = 1 if off > 0 else -1
        ticks = min(max_ticks, max(1, int(abs(off) / 0.6)))
        return {"turns": direction, "turn_ticks": ticks, "forward_ticks": 0,
                "jump": False}
    fwd = min(max_ticks, max(3, int(dist / 1.5)))   # ~1.5yd per tick conservative
    return {"turns": 0, "turn_ticks": 0, "forward_ticks": fwd,
            "jump": True}                            # hop possible fences


def execute(env, player_pos, target_pos, facing, legs=6, arrive_dist=4.0):
    """Run up to `legs` plan-and-move cycles via env._raw_move. Returns final pos."""
    import time
    pos = list(player_pos)
    for _ in range(legs):
        plan = plan_leg(pos, target_pos, facing, arrive_dist=arrive_dist)
        if plan is None:
            break
        if plan["turns"]:
            kind = "turnLeft" if plan["turns"] > 0 else "turnRight"
            for _ in range(plan["turn_ticks"]):
                env._raw_move(kind)
        if plan["forward_ticks"]:
            for _ in range(min(plan["forward_ticks"], 5)):
                env._raw_move("forward")
        info = getattr(env, "_last_info", None) or {}
        pos = info.get("player_pos") or pos
        facing = info.get("player_facing", facing) if isinstance(info, dict) else facing
    return pos
