"""Derived navigation features from the EXISTING observation vector.

This module does NOT add anything to the game observation. It only extracts
extra navigation labels from fields that obs.ts already exposes
(relative sin/cos of nearest mob and selected target). Used for BC training /
error analysis only.

Obs layout (src/sim/obs.ts, verified 2026-08-13):
  self(16) | abilities(ABILITY_SLOTS*2) | target(9 @TGT) |
  nearby_mobs(5*6 @MOBS) | interact(5) | quests(QUEST_ORDER*2) | paladin(3)

target block (9): [0]=has, [1]=hp, [2]=level, [3]=dist/40,
                   [4]=sin, [5]=cos, [6]=hostile, [7]=lootable, [8]=aggro
mob block (6 each): [0]=dist/40, [1]=sin, [2]=cos, [3]=hp,
                    [4]=level, [5]=aggro

ABILITY_SLOTS is NOT a constant in obs.ts (it is derived from CLASSES), so the
caller must pass it explicitly. We refuse to hardcode it.
"""
from __future__ import annotations

from dataclasses import dataclass

# distance scale used everywhere in obs.ts: d/40, ceiling 1.5 (=60yd radius)
DIST_SCALE = 40.0
MOB_SAT = 1.5
MELEE_YD = 6.0

# Hysteresis band for combat-range detection (yards). Entered at/below
# COMBAT_ENTER_YD, left only above COMBAT_EXIT_YD, so the boolean does NOT
# dither at the ~5yd melee boundary. Root cause of A's COMBAT-mode loss is the
# raw sin/cos signal never giving a stable "stop and attack" latch; this feature
# supplies exactly that latch. Bands chosen from MELEE_RANGE~5yd (observed) with a
# 2yd exit margin so transient range jitter cannot flip the mode.
COMBAT_ENTER_YD = 5.0
COMBAT_EXIT_YD = 7.0


@dataclass
class NavFeatures:
    mob_visible: bool
    mob_dist: float           # raw yards (dist/40 * 40)
    mob_sin: float
    mob_cos: float

    turn_dir: int             # -1 / 0 / +1 (sign of mob_sin w/ deadband)
    turn_strength: float      # abs(mob_sin)
    forward_ok: bool          # mob roughly in front

    target_has: bool
    target_dist: float        # raw yards
    target_sin: float
    target_cos: float

    phase: str                # SEARCH/NAV/ACQUIRE/APPROACH/COMBAT/DEAD
    in_combat_range: bool = False  # hysteresis latch (see CombatRangeTracker)


class CombatRangeTracker:
    """Stateful hysteresis latch for 'in combat range'.

    Stateless make_nav_features cannot hold per-episode state, so the caller
    owns one tracker per episode (dataset collection AND eval rollout) and feeds
    its .in_combat boolean into make_nav_features. Resets to False whenever the
    target is lost (death/re-target), so post-death re-engage does not inherit a
    stale latch.
    """

    def __init__(self, enter: float = COMBAT_ENTER_YD, exit: float = COMBAT_EXIT_YD):
        self.in_combat = False
        self.enter = enter
        self.exit = exit

    def update(self, target_has: bool, target_dist: float) -> bool:
        if not target_has:
            self.in_combat = False
            return False
        if self.in_combat:
            if target_dist > self.exit:
                self.in_combat = False
        else:
            if target_dist <= self.enter:
                self.in_combat = True
        return self.in_combat


def sign_deadband(x: float, deadband: float = 0.15) -> int:
    if x > deadband:
        return 1
    if x < -deadband:
        return -1
    return 0


def decode_nav_obs(obs, ability_slots: int):
    """Decode navigation fields. ability_slots MUST be supplied by caller.

    Returns dict with raw decoded mob/target signals (pre-feature)."""
    if ability_slots is None:
        raise RuntimeError("Pass ability_slots explicitly; do not hardcode it.")
    tgt = 16 + ability_slots * 2
    mobs = tgt + 9

    def decode_target():
        t = obs[tgt:tgt + 9]
        has = int(round(float(t[0]))) == 1
        return {
            "has": has,
            "hp": float(t[1]),
            "dist": float(t[3]) * DIST_SCALE,   # yards
            "sin": float(t[4]),
            "cos": float(t[5]),
            "hostile": int(round(float(t[6]))),
            "aggro": int(round(float(t[8]))),
        }

    def decode_mob():
        m = obs[mobs:mobs + 6]
        if float(m[0]) >= MOB_SAT:
            return None  # no mob in 60yd
        return {
            "dist": float(m[0]) * DIST_SCALE,
            "sin": float(m[1]),
            "cos": float(m[2]),
            "hp": float(m[3]),
            "aggro": int(round(float(m[5]))),
        }

    return decode_target(), decode_mob()


def make_nav_features(
    *,
    mob_dist: float,
    mob_sin: float,
    mob_cos: float,
    target_has: bool,
    target_dist: float,
    target_sin: float,
    target_cos: float,
    dead: bool = False,
    in_combat_range: bool = False,
) -> NavFeatures:
    mob_visible = mob_dist < MOB_SAT * DIST_SCALE  # <60yd

    turn_dir = sign_deadband(mob_sin)
    turn_strength = abs(mob_sin)
    # cos tells us whether the mob is roughly in front; NOT used as an action.
    forward_ok = mob_cos > 0.35

    if dead:
        phase = "DEAD"
    elif target_has and target_dist <= MELEE_YD:
        phase = "COMBAT"
    elif target_has:
        phase = "APPROACH"
    elif mob_visible:
        phase = "NAV"
    else:
        phase = "SEARCH"

    return NavFeatures(
        mob_visible=mob_visible,
        mob_dist=mob_dist,
        mob_sin=mob_sin,
        mob_cos=mob_cos,
        turn_dir=turn_dir,
        turn_strength=turn_strength,
        forward_ok=forward_ok,
        target_has=target_has,
        target_dist=target_dist,
        target_sin=target_sin,
        target_cos=target_cos,
        phase=phase,
        in_combat_range=in_combat_range,
    )
