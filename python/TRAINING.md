# Training — Hierarchical PPO (Step 6 of adapter plan)

High-level PPO policy learns to **select skills** (farm / loot / sell_junk /
accept_quest / turn_in_quest / gather / craft / heal / equip / buy); the low-level
layer (B1 / obs.ts ACTIONS) executes them. This is the "lifelong / hierarchical"
layer the repo itself does NOT ship — world-of-claudecraft only provides the flat
PPO-on-obs.ts infra (`wow_env.py`, `example_random_agent.py`).

## World population — RESOLVED (Step 7)
`WoWClassicEnv.reset(seed=...)` DOES populate the world: `new Sim()` from
`src/sim/sim.ts` yields **967 entities (704 hostile mobs, 107 NPCs, 155 objects),
camps=207**. Earlier "empty world / 0 kills" was a probe bug — `encodeObs` only
includes mobs within radius 60 of the player; spawn is at `[2,-2]`, nearest mob
~46u away. The `farm` skill must NAVIGATE to the mob zone (target → turn → forward
→ wall-follow) before attacking. See CAPABILITY_MATRIX.md.

## Skill set (must match SKILLS in agent_core.ts + VERIFIERS in verifiers.ts)
```
0 farm          1 loot          2 accept_quest
3 turn_in_quest 4 sell_junk     5 gather
6 craft         7 heal          8 equip  9 buy
```
Each skill has: `preconditions`, `execute`, `handle`, and is verified by
`verifySkill(name, {before, after, handle})` (the single VERIFY layer). Do NOT
add `success_condition/failure_condition` to Skill — verifiers.ts is the only
source of truth.

## Files
- `hierarchical_env.py` — `HierarchicalWoWEnv(gym.Env)`: high-level obs +
  `Discrete(N_SKILLS)` action (skill id) + reward from `info` deltas. Each
  high-level step runs a sub-sequence of low-level `WoWClassicEnv.step()` calls.
- `train_hierarchical.py` — SB3 PPO trainer. Saves `models/hl_ppo/final.zip`.
- `test_skills_headless.py` — deterministic end-to-end chains (Phase C).

## GPU (TheRock / ROCm)
Use the dedicated venv, NOT the system python (CPU-only). PYTHONPATH from the
Hermes agent leaks a conflicting numpy — unset it:
```bash
cd python
env -u PYTHONPATH /d/woc-llm/therock-test/Scripts/python.exe train_hierarchical.py \
    --steps 20000 --out models/hl_ppo --max_steps 500
# torch 2.12.0+rocm7.15, cuda_avail=True, SB3 2.9.0
```

## Attach trained weights to the live agent
In `agent_core.ts` the high-level policy is an optional override:
```ts
import { setHlPolicy } from './agent_core';
setHlPolicy((ws) => pickSkillFromPPO(ws)); // your loaded SB3 model wrapper
```
When `hlPolicy` is set, `step()` uses it instead of the Goal Manager.

## Training order (per plan)
1. Phase A — fix verifiers (DONE: gather/craft/equip/loot/quest handle-correct).
2. Phase B — full Skill Library (DONE: 9 skills, verifySkill-integrated).
3. Phase C — deterministic headless chains (FARM→LOOT, FARM→LOOT→SELL, etc.)
   MUST all return SUCCESS before any PPO.
4. Phase D — only then train high-level PPO on the full 9-skill space.

## Known gap (honest)
Low-level navigation to mobs still needs wall-follow (same gap as live).
PPO baseline not yet produced — navigation instability crashed the node server
during a 20k run. Fix Phase C chains first; PPO is the LAST step.
