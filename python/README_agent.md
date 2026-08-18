# Headless RL Warrior Agent

Rule-based (hand-written heuristic) agent for World of Claudecraft, driving the
same deterministic Sim the game client uses via the Gymnasium wrapper.

## Setup (Windows, MSYS/bash)
```bash
cd /d/world-of-claudecraft
export PATH="$PATH:/c/Users/vladc/AppData/Roaming/npm"
# 1. bundle the env server (esbuild only; no full pnpm install needed)
esbuild headless/env_server.ts --bundle --platform=node --format=cjs --outfile=dist-env/env_server.cjs
# 2. python deps
python -m pip install gymnasium numpy
```

## Run
```bash
python python/simple_warrior_agent.py
```
Prints per-episode: steps, reward, level, xp, kills, deaths, quests.

## Result (verified, seed sweep)
- obs size 567, 61 discrete actions
- On seeds 1003/1004 the agent kills 3 mobs, gains ~180 XP, dies once.
- Other seeds wander without finding a mob in 5000 steps (spawn area is large;
  navigation is naive forward + periodic veer).

## Observation layout (src/sim/obs.ts)
- self: 0..15
- abilities: 16 .. 16+2*N  (N = ability slots; [ready, cd_frac] per slot)
- target: +9  (has, hpFrac, lvlDiff, dist/40, sin(rel), cos(rel), hostile, lootable, aggro)
- mobs: +30  (5 mobs * 6: dist/40, sin(rel), cos(rel), hpFrac, lvlDiff, aggro)
- interactable: +5  (has, dist/40, sin, cos, type)  .33=corpse .66=object 1=npc
- quests: +2*Q
- paladin: +3

`rel = angleTo(entity) - facing`; sin≈0 & cos≈1 → entity dead ahead.

## Policy summary
1. HP < 45% → eat/drink
2. has target → approach (turn if off-heading, else forward); in melee → abilities + attack
3. no target → forward + periodic target_nearest; veer every 15 steps to sweep

## Notes
- `target_nearest` only locks a hostile within the Sim's acquisition radius
  (~38yd ≈ obs dist/40 < 0.95). Movement is what provokes aggro; the hostile
  then walks into melee on its own.
- This is a baseline heuristic, NOT a trained policy. For real RL, wrap
  `WoWClassicEnv` with stable-baselines3 PPO (obs is a flat Box, action is
  Discrete(61)). Reward per step is already a weighted delta of xp/dmg/kills/etc.
