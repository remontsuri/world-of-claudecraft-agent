"""Rule-based warrior agent for World of Claudecraft headless env.

Reads the documented observation layout (src/sim/obs.ts) and issues discrete
actions. Priorities: survive (eat/drink) > fight nearest hostile > loot a fresh
corpse > wander to find a mob.

Observation layout (indices from obs.ts), offsets resolved at startup:
  self        : 0..15
  abilities    : 16 .. 16+2*N   (N = ability slots; [ready, cd_frac] per slot)
  target       : +9   (has, hpFrac, lvlDiff, dist/40, sin, cos, hostile, lootable, aggro)
  mobs         : +30  (5 mobs * 6: dist/40, sin(rel), cos(rel), hpFrac, lvlDiff, aggro)
  interactable : +5   (has, dist/40, sin, cos, type)  .33=corpse .66=object 1=npc
  quests       : +2*Q
  paladin      : +3
"""

from __future__ import annotations

import time

import numpy as np

from wow_env import WoWClassicEnv

_step = 0


def resolve_offsets(action_names: list[str]) -> dict:
    n_abilities = sum(1 for a in action_names if a.startswith("ability_"))
    self_n = 16
    abilities_n = n_abilities * 2
    target_off = self_n + abilities_n
    mobs_off = target_off + 9
    interact_off = mobs_off + 5 * 6
    return {
        "self_n": self_n,
        "target_off": target_off,
        "mobs_off": mobs_off,
        "interact_off": interact_off,
    }


def _nav(obs: np.ndarray, base: int):
    return obs[base + 3], obs[base + 4], obs[base + 5]  # dist_frac, sin, cos


def policy(obs: np.ndarray, off: dict, a: dict) -> int:
    # 1) survive
    if obs[0] < 0.45:
        return a["eat_drink"]

    to = off["target_off"]
    has_target = obs[to] > 0.5

    # 2) fight: if we have a target, approach + engage
    in_combat = obs[12] > 0.5
    if has_target:
        dist, sin_r, cos_r = _nav(obs, to)
        lootable = obs[to + 7] > 0.5  # target is a lootable corpse -> loot it
        if lootable and dist < 0.15:
            return a["interact"]
        if dist > 0.25:
            if cos_r < 0.985:
                return a["turn_left"] if sin_r > 0 else a["turn_right"]
            return a["forward"]
        # in melee: never move (don't break auto-attack); spam abilities + attack
        for slot in (0, 1, 2):
            if obs[16 + slot * 2] > 0.5:
                return a[f"ability_{slot + 1}"]
        return a["attack"]

    # 3) no target yet: walk forward to provoke aggro; the hostile then closes
    # in and target_nearest can lock it. Periodically ping target_nearest (it is
    # a no-op when nothing is in acquisition range) and occasionally veer so we
    # don't march off in a straight line away from the spawn mobs.
    global _step
    _step += 1
    mo = off["mobs_off"]
    mdist = obs[mo + 3]
    if mdist < 1.5:  # something within 60yd: keep trying to acquire + approach
        if _step % 2 == 0:
            return a["target_nearest"]
        return a["forward"]
    # nothing in sight: wander, veering every ~15 steps to sweep the area
    if _step % 15 == 0:
        return a["turn_right"]
    return a["forward"]

    # (looting handled inside the target branch for a killed mob)
    # if a standalone corpse sits in interact range with no live target:
    io = off["interact_off"]
    if obs[io] > 0.5 and obs[io + 4] < 0.5 and obs[io + 1] < 0.15:
        return a["interact"]
    return a["forward"]


def run(episodes: int = 6, seed0: int = 1000, max_steps: int = 5000) -> None:
    env = WoWClassicEnv(player_class="warrior", max_steps=max_steps)
    off = resolve_offsets(env.action_names)
    a = {name: i for i, name in enumerate(env.action_names)}
    a = {
        "eat_drink": a["eat_drink"],
        "interact": a["interact"],
        "forward": a["forward"],
        "turn_left": a["turn_left"],
        "turn_right": a["turn_right"],
        "target_nearest": a["target_nearest"],
        "attack": a["attack"],
        "ability_1": a["ability_1"],
        "ability_2": a["ability_2"],
        "ability_3": a["ability_3"],
    }
    print(f"obs={env.observation_space.shape[0]} actions={env.action_space.n} off={off}")

    total = 0.0
    for ep in range(episodes):
        obs, info = env.reset(seed=seed0 + ep)
        ep_r = 0.0
        t0 = time.perf_counter()
        steps = 0
        while True:
            act = policy(obs, off, a)
            obs, reward, term, trunc, info = env.step(act)
            total += reward
            ep_r += reward
            steps += 1
            if term or trunc:
                break
        print(
            f"ep{ep}: steps={steps} reward={ep_r:.1f} lvl={info.get('level')} "
            f"xp={info.get('xp')} kills={info.get('kills')} deaths={info.get('deaths')} "
            f"quests={info.get('quests_done')} ({time.perf_counter() - t0:.1f}s)"
        )
    print(f"TOTAL reward: {total:.1f}")
    env.close()


if __name__ == "__main__":
    run()
