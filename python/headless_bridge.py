"""Headless proof of the unified Agent Bridge.

Runs the SAME ScriptedController + encodeObs path the browser bridge will use,
just against the headless Sim (WoWClassicEnv) instead of window.__game. This
proves the controller logic and obs decoder are correct BEFORE we point the
bridge at the live online character. If this produces stable kills, the only
remaining unknown is whether window.__game.controller drives the online char
(the CDP login blocker) -- not the agent logic itself.

Run:  python python/headless_bridge.py --mode scripted --max-steps 6000
"""

from __future__ import annotations

import argparse
import numpy as np

from wow_env import WoWClassicEnv
from scripted_agent import ScriptedController

# obs layout from src/sim/obs.ts (encodeObs):
#   target block starts at index 43, 9 wide:
#     [has, hp, lvl_rel, dist/40, sin(rel), cos(rel), hostile, dead_loot, aggro]
TARGET_OFF = 43
MOB_OFF = 52  # 5 mobs x 6


def decode_target(obs: np.ndarray, info: dict) -> dict | None:
    # Prefer explicit telemetry from env_server (targetId/targetDist/targetOffDeg),
    # set via the patched infoDict. Falls back to obs target block if absent.
    tid = info.get("targetId")
    if tid is None:
        # obs target block at index 43: [has, hp, lvl_rel, dist/40, sin, cos, ...]
        if len(obs) > 51 and obs[43] > 0.5:
            dist = obs[46] * 40.0
            off = np.degrees(np.arctan2(obs[47], obs[48]))
            return {"has": True, "dist": float(dist), "off_deg": float(off), "hp": float(obs[44]) * 100, "id": None}
        return None
    dist = info.get("targetDist")
    off = info.get("targetOffDeg")
    if dist is None or off is None:
        return None
    return {"has": True, "dist": float(dist), "off_deg": float(off), "hp": 100.0, "id": tid}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="scripted")
    ap.add_argument("--player-class", default="warrior")
    ap.add_argument("--max-steps", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    env = WoWClassicEnv(player_class=args.player_class)
    ctrl = ScriptedController(action_names=env.action_names)
    obs, info = env.reset(seed=args.seed)

    kills = 0
    prev_kills = 0
    damage = 0
    deaths = 0
    prev_deaths = 0
    states = {}
    last_state = None

    for step in range(args.max_steps):
        target = decode_target(obs, info)
        action, state = ctrl.decide(obs, target)
        states[state] = states.get(state, 0) + 1
        last_state = state
        obs, reward, terminated, truncated, info = env.step(action)
        kills = info.get("kills", 0)
        deaths = info.get("deaths", 0)
        damage = info.get("damageDealt", 0)
        if step % 200 == 0 or (kills > prev_kills) or (deaths > prev_deaths):
            tdist = target['dist'] if target else 0.0
            toff = target['off_deg'] if target else 0.0
            tmark = '-' if not target else f"{tdist:.1f}"
            omark = '-' if not target else f"{toff:.0f}"
            print(
                f"[t+{step:4d}] state={state:9s} act={action:2d} "
                f"kills={kills} deaths={deaths} dmg={damage:.0f} "
                f"hp={float(info.get('hp', 0)):.0f} "
                f"dist={tmark} off={omark}"
            )
        prev_kills, prev_deaths = kills, deaths
        if terminated or truncated:
            print(f"[reset] terminated={terminated} truncated={truncated}")
            obs, info = env.reset(seed=args.seed)

    print("\n=== RESULT ===")
    print(f"kills={kills} deaths={deaths} damage={damage:.0f}")
    print(f"state histogram: {states}")
    print(f"final state: {last_state}")
    env.close()

    if kills >= 2:
        print("[PASS] ScriptedController + encodeObs produce stable kills headless.")
    else:
        print("[WARN] kills < 2 -- controller still needs work before browser.")


if __name__ == "__main__":
    main()
