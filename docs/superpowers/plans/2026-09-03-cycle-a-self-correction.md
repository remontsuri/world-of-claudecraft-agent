# WoC Cycle A — Self-Correcting Autonomy Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Agent in `remontsuri/world-of-claudecraft-agent` runs `D:\woc-game` (offline) and proves ACCEPT → 8 kills → TURN_IN → next quest cycle with truthful learning.

**Architecture:** Existing pipeline: GAME → bridge → WorldState → Observation → Policy/Q → Skill → bridge → GAME → reward → memory. Minimal fix only to make cycle A self-correcting.

**Tech Stack:** Python 3.11, Node.js, CDP (Chrome 9222), Vite 5173, Bridge 8791.

**Spec:** /GOAL (2026-09-03 user message).

**Game source of truth:** `D:\woc-game\src\sim\obs.ts` (low-level action space: forward, turn_left, turn_right, attack, target_nearest, abilities).

**Repo source of truth:** HEAD `fe58c5257` on `mine/backup`.

---

## Phase 0: Baseline Snapshot (DONE)

Live state observed 2026-09-03 ~14:00 MSK:
- Vite PID 5376 (port 5173)
- Bridge PID 20112 (port 8791) — game: true
- Chrome PID 11076 (port 9222) — page alive
- Player: hp=100, pos=(0.14, -0.14), facing=-0.79
- Active quest: **q_boars 0/5** (auto-accepted by player who entered world)
- 8 forest_wolf hostile mobs at 50-85yd
- kills=0, deaths=0, quests_done=0

## Phase 1: Investigate RED — Why kills=0 despite farm step

**Files:** `python/play_autonomous.py:481-520` (run loop), `python/agent.py:480-515` (survival overrides), `src/bridge/actions.cjs:85-200` (case 0 farm).

**Step 1.1:** Read policy.py `decide()` lines 90-101 (PHASE_ALLOWED) + lines 47-83 (hard overrides).

**Step 1.2:** Verify the action space: PHASE_DO_OBJECTIVE allows `farm, loot, gather, cast, craft, sell` but **NOT `explore`**. So if agent picks `explore` during DO_OBJECTIVE, it must be via override or fallback.

**Step 1.3:** Identify the "explore loop" cause: `policy.py` may be returning explore when state has no nearby mob (no mob in `nearby[].hostile`). Fix: explore must transition to `farm_within_detection_range` (move toward mob spawn area).

## Phase 2: Farm Distance — RED

**RED test:** wolf at 50yd should close to ≤7yd in <10s of farm step.

**Step 2.1:** Write `python/test_chase_farm_50yd.py` — fresh boot, accept q_wolves, run farm step, measure distance.

**Step 2.2:** Run live. Expected: RED if distance doesn't close.

**Step 2.3:** If RED, trace `actions.cjs:case 0` line 168: `g.controller.move({turnLeft/right, forward: d>3}, desired)`. The 2nd arg `desired` IS being passed (commit 71982e457). But test may show 2nd arg is `undefined` (snake_case vs camelCase). Verify.

**Step 2.4:** If 2nd arg is wrong, fix `actions.cjs:case 0:155-185` to pass `bearing_diff`-computed `desired_facing` correctly.

## Phase 3: Self-Correction in Policy

**RED:** When `farm` returns INCONCLUSIVE (no mob found in range) twice in a row, agent should NOT keep calling `farm` (wastes step). It should either: (a) navigate toward mob spawn zone, or (b) explore the area.

**Step 3.1:** Read `python/policy.py:decide()` to confirm current "fallback to explore" path.

**Step 3.2:** Add self-correction rule: if `farm` returned INCONCLUSIVE 3+ times in same Q-bucket, force `navigate` toward quest objective (not explore).

**Step 3.3:** Test: `python/test_policy_farm_fallback.py`.

## Phase 4: Full Cycle A Acceptance

**Step 4.1:** Clean state: kill agent, `rm python/experience_autonomous.json python/replay_buffer.json python/strategy_memory.json python/world_memory.json python/self_reflection.json`.

**Step 4.2:** Re-enter world via CDP (user does this manually).

**Step 4.3:** Start `play_autonomous.py` in background. Target: 1 quest completed within 30 min.

**Step 4.4:** Poll every 60s, log: step#, action, dist, hp, kills, deaths, q_wolves 0/8 → 8/8.

**Step 4.5:** If cycle A passes (8/8 + turn_in), celebrate. If RED, go to Phase 5.

## Phase 5: Long-Horizon (DEFER until Phase 4 passes)

5000 steps, 10+ quests_done, deaths/1000 ≤ 2.0, heal rate ≥ 0.70.

## Phase 6: Multi-Quest (DEFER until Phase 4 passes)

q_wolves → q_boars → q_bandits → q_prof_workorder_forge (collect). No hardcoded NPC names.

---

## Global Constraints

- **GAME IS SOURCE OF TRUTH** — never invent APIs.
- **NO TELEPORT** — use `controller.move`.
- **NO SECOND PLANNER/NAVIGATOR/GOAL WRITER/COMBAT CONTROLLER** — extend existing.
- **NEVER KILL** Vite/Chrome/tab — only reload tab via CDP, restart only Bridge/Agent.
- **ALWAYS COMMIT** at task boundary. HEAD must be on `mine/backup`.
- **ALWAYS READ** `python/memory.py:_bucket()` before changing decision logic.

