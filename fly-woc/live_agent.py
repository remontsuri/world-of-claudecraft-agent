#!/usr/bin/env python3
"""Live MaleCNS/Fly controller for the real WoC 61-action wire.

The committed PPO checkpoint was trained against src/sim/obs.ts ACTIONS.  The
legacy online BrowserEnv.step() API is a 10-skill capability API and must not
receive these action IDs.  This runner therefore talks to the bridge's
action=rl_step endpoint.
"""
from __future__ import annotations

import argparse
import json
import math
import urllib.request
from pathlib import Path
import sys

import numpy as np
import torch

ACTIONS = (
    ["noop", "forward", "back", "turn_left", "turn_right", "strafe_left",
     "strafe_right", "jump", "target_nearest", "attack"]
    + [f"ability_{i}" for i in range(1, 49)]
    + ["interact", "stop", "eat_drink"]
)
assert len(ACTIONS) == 61


class Bridge:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def call(self, payload: dict) -> dict:
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            out = json.loads(response.read())
        if not out.get("ok"):
            raise RuntimeError(out.get("error", "bridge error"))
        return out

    def snapshot(self) -> dict:
        return self.call({"action": "snapshot"})["info"]

    def step(self, action: int) -> dict:
        return self.call({"action": "rl_step", "idx": int(action)})["info"]


def angle_diff(a: float, b: float) -> float:
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def live_features(info: dict) -> np.ndarray:
    """Build the same 13 v2 semantic channels from the compact live snapshot."""
    p = info.get("player", {}) or {}
    pos = info.get("player_pos", [0.0, 0.0])
    nearby = info.get("nearby", []) or []
    facing = float(p.get("facing", 0.0))

    hp = float(p.get("hp", 0.0))
    max_hp = max(float(p.get("maxHp", 100.0)), 1.0)
    resource = float(p.get("resource", 0.0))
    max_resource = max(float(p.get("maxResource", 100.0)), 1.0)

    target_id = p.get("targetId")
    target = (
        next((e for e in nearby if str(e.get("id")) == str(target_id)), None)
        if target_id is not None else None
    )
    mobs = [
        e for e in nearby
        if (e.get("kind") or e.get("type")) == "mob"
        and e.get("hostile", True)
        and not e.get("dead", False)
    ]
    mob = min(mobs, key=lambda e: e.get("dist", 999.0), default=None)

    interactables = [
        e for e in nearby
        if (
            (e.get("lootable") and not e.get("looted", False))
            or (
                (e.get("kind") or e.get("type")) == "npc"
                and (e.get("questIds") or e.get("questId"))
            )
        )
    ]
    interactable = min(
        interactables, key=lambda e: e.get("dist", 999.0), default=None
    )

    def relative_angle(entity: dict) -> float:
        dx = float(entity.get("x", 0.0)) - pos[0]
        dz = float(entity.get("z", 0.0)) - pos[1]
        # WoC convention: facing=0 points +Z.
        return angle_diff(math.atan2(dx, dz), facing)

    def encode_target(entity: dict | None) -> tuple[float, float, float]:
        if not entity:
            return 0.0, 0.0, 0.0
        distance = min(float(entity.get("dist", 999.0)), 60.0) / 60.0
        rel = relative_angle(entity)
        return (
            distance,
            (math.sin(rel) + 1.0) / 2.0,
            (math.cos(rel) + 1.0) / 2.0,
        )

    target_dist, target_sin, target_cos = encode_target(target)
    mob_dist, mob_sin, mob_cos = encode_target(mob)

    active = info.get("quests", {}).get("active", []) or []
    ready = info.get("quests", {}).get("ready", []) or []
    if ready:
        quest_signal = 1.0
    elif active:
        progress = []
        for quest in active:
            for objective in quest.get("objectives", []) or []:
                current = float(objective.get("current", 0))
                required = max(float(objective.get("required", 1)), 1.0)
                progress.append(min(current / required, 1.0))
        quest_signal = max(progress, default=0.0)
    else:
        quest_signal = 0.0

    interact_proximity = 0.0
    if interactable:
        interact_proximity = max(
            0.0, 1.0 - min(float(interactable.get("dist", 60.0)) / 5.0, 1.0)
        )

    return np.asarray(
        [
            hp / max_hp,
            resource / max_resource,
            float(p.get("inCombat", info.get("in_combat", False))),
            1.0 - float(float(p.get("gcdRemaining", 0.0)) > 0.0),
            float(target is not None),
            target_dist,
            target_sin,
            target_cos,
            mob_dist,
            mob_sin,
            mob_cos,
            interact_proximity,
            quest_signal,
        ],
        dtype=np.float32,
    )


def oracle_extra_live(info: dict, table: dict) -> np.ndarray:
    """Build the 5-channel oracle side input directly from the live snapshot."""
    p = info.get("player", {}) or {}
    x, z = map(float, info.get("player_pos", [0.0, 0.0]))
    facing = float(p.get("facing", 0.0))
    active = info.get("quests", {}).get("active", []) or []
    ready = info.get("quests", {}).get("ready", []) or []

    candidates = []
    if ready:
        for q in ready:
            qid = q.get("id") or q.get("questId")
            if qid:
                candidates.append((qid, "ready", 1.0))
    for q in active:
        qid = q.get("id") or q.get("questId")
        if not qid:
            continue
        progress = 0.0
        objectives = q.get("objectives", []) or []
        if objectives:
            progress = max(
                (
                    min(
                        float(o.get("current", 0))
                        / max(float(o.get("required", 1)), 1.0),
                        1.0,
                    )
                    for o in objectives
                ),
                default=0.0,
            )
        candidates.append((qid, "active", progress))

    if not candidates:
        return np.asarray([1.5, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)

    qid, state, progress = candidates[0]
    quest = table.get("quests", {}).get(qid, {})
    target = None
    if state == "ready":
        target = quest.get("turnIn")
    else:
        objectives = quest.get("objectives") or []
        if objectives:
            idx = min(int(progress * len(objectives)), len(objectives) - 1)
            for j in list(range(idx, len(objectives))) + list(range(0, idx)):
                if objectives[j].get("area"):
                    target = objectives[j]["area"]
                    break
        if target is None:
            target = quest.get("giver")

    if not target:
        return np.asarray([1.5, 0.0, 0.0, 1.0 if state == "active" else 0.0,
                           1.0 if state == "ready" else 0.0], dtype=np.float32)

    dx = float(target["x"]) - x
    dz = float(target["z"]) - z
    dist = math.hypot(dx, dz)
    rel = angle_diff(math.atan2(dx, dz), facing)
    return np.asarray(
        [
            min(dist / 40.0, 1.5),
            math.sin(rel),
            math.cos(rel),
            1.0 if state == "active" else 0.0,
            1.0 if state == "ready" else 0.0,
        ],
        dtype=np.float32,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge", default="http://127.0.0.1:8791")
    parser.add_argument("--model", default="outputs/params_fly_v2.pt")
    parser.add_argument("--circuit", default="data/circuit.json")
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--deterministic", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    from fly_brain import FlyBrain
    from agent import FlyBrainReadout
    from device_utils import describe_device, resolve_device

    bridge = Bridge(args.bridge)
    dev = resolve_device(getattr(args, "device", None))
    brain = FlyBrain(args.circuit, device=dev)
    print(f"[fly-live] {brain.describe()}", flush=True)
    state = torch.load(root / args.model, map_location=dev, weights_only=False)
    checkpoint = state if isinstance(state, dict) else {}
    state = checkpoint.get("state", checkpoint.get("state_dict", state))
    actor0 = state.get("actor.0.weight") if isinstance(state, dict) else None
    extra = 5 if actor0 is not None and int(actor0.shape[1]) == brain.n_dn + 5 else 0
    oracle_table = None
    if extra:
        from quest_oracle import load_table
        oracle_table = load_table()
        print("[fly-live] oracle side channel detected (+5)")
    network = FlyBrainReadout(brain.n_dn + extra, 61).to(dev)
    network.load_state_dict(state, strict=True)
    network.eval()
    brain.reset(1)

    info = bridge.snapshot()
    print(f"[fly-live] bridge OK; n_dn={brain.n_dn}")

    for step in range(args.steps):
        features = live_features(info)
        dn = brain.step(torch.as_tensor(features[None, :], device=dev))
        if extra:
            oracle = torch.as_tensor(oracle_extra_live(info, oracle_table)[None, :], device=dev)
            dn = torch.cat([dn, oracle], dim=1)
        logits, _ = network(dn)
        logits = logits[0] / max(args.temperature, 1e-3)

        if args.deterministic:
            action = int(torch.argmax(logits))
        else:
            action = int(torch.distributions.Categorical(logits=logits).sample())

        info = bridge.step(action)

        if step % 10 == 0:
            player = info.get("player", {})
            print(
                f"[{step:5d}] action={action:2d} {ACTIONS[action]:16s} "
                f"hp={player.get('hp', 0):.0f} "
                f"pos={info.get('player_pos')} "
                f"kills={info.get('kills', 0)} "
                f"quests={info.get('quests_done', 0)}"
            )

        if player.get("dead"):
            print("[fly-live] dead; stopping for safety")
            break


if __name__ == "__main__":
    main()
