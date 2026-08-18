# WoC Self-Learning Agent — STATUS

## Last verified run: 2026-08-17 (online browser agent, browser_bridge + BrowserEnv)

### What we proved (and stopped chasing)

**B3 / B4 were DIAGNOSTIC UNIT TESTS of the learning mechanism — not the goal.**
They proved the core loop works in the *headless* sim:
  world → action → real consequence → memory → Q change → behaviour change.
But they were circling `P(return|far)`, which is the wrong optimization target.
Per user direction 2026-08-17: stop perfecting B3, move to the real autonomous
agent in the ONLINE world.

**Verdict on the mechanism (architecture ~95%, loop ~90%):**
- bucket-mismatch bug (decide/learn key mismatch) — FIXED, verified.
- memory persistence — FIXED, verified.
- count-based exploration no-op — FIXED, verified.
- return_to_giver waypoint bug — FIXED (now navigates directly to giver).
- Negative learning proven: Q(farm) 0 → −0.535 from real drift consequence.
- return_to_giver physically useful: closes 81.7→3.7, reward +1.19 (isolated diag).
- P(return) as a gate: NOT proven (mala N, rare-positive exploration). This is a
  MEASUREMENT/exploration limit, not an architecture failure. We intentionally
  did NOT chase P(return)=0.72 — see user's Level-3 redirect.

### Level 3 — ONLINE AUTONOMOUS AGENT (the actual target)

The agent now runs against the REAL online WoC world via the browser, not the
local headless sim.

**Wiring (no Sim/policy/reward changes — pure I/O adapter):**
- `browser_bridge.cjs` — node/puppeteer-core bridge: connects CDP :9222, reads
  `window.__game.sim` as observation, applies actions via `g.controller.move /
  sim.targetEntity / sim.startAutoAttack / sim.interact`, serves a flat `info`
  dict over HTTP :8791. Reuses the existing `agent_browser.mjs` / `bridge_online`
  pattern.
- `browser_env.py` — Python `BrowserEnv` implementing the SAME interface
  `HierarchicalWoWEnv` exposes (`step(idx)`, `_last_info`, `_navigate_to_coord`,
  `base.step(ACT_*)` for explore). `Agent` and `play_autonomous.py` run UNCHANGED.
- `play_autonomous.py` — persistent session: reset → observe → decide → act →
  learn → repeat, no forcing functions, no `if quest/far/mob` scripts. Metrics
  track behaviour development (kills, quests, deaths, explored_cells, actions),
  not P(return).

**Run results (3000 steps, online, two sessions):**
- Agent lives in the live world, chooses its own actions (farm/explore/loot/
  sell/heal distributed), 0 env_errors, memory persists.
- respawn glue works: on death → releaseSpirit + resurrectAtSpiritHealer, loop
  continues (hp recovers 0.2→1.0).
- explored_cells grew (14 at 250 steps in session 1; session 2 the character
  respawned at the graveyard and stayed near spawn — see LIMIT below).

**LIMIT (honest, not a blocker):** the agent does not yet traverse the large
world aggressively. `explore` = 1 raw forward step per call, and `farm` only
acquires mobs within 45yd. Near the spawn/graveyard there are few mobs, so
kills plateau and the agent lingers. This is a NAVIGATION/exploration-tuning
gap, not a learning-loop failure. Next step: make `explore` walk a sustained
bearing (or navigate toward detected mobs/NPCs) so the agent actually covers
ground and discovers content.

### How to reproduce (online)
```bash
# 1. Browser open on worldofclaudecraft.com, Chrome with remote debugging (:9222)
# 2. start the bridge (serves :8791)
cd D:/world-of-claudecraft
node browser_bridge.cjs
# 3. run the autonomous agent (talks to the bridge)
cd D:/world-of-claudecraft/python
export PYTHONPATH=""
python play_autonomous.py        # AUTONOMOUS_STEPS / SAVE_EVERY env-overridable
# log -> autonomous_log.jsonl ; memory -> experience_autonomous.json
```

### Infra note
The headless sim server is SHARED (single per machine) — B3/B4 could not
parallelize. The ONLINE path has no such limit: the browser is the world. GPU
(TheRock) does not help the tabular agent; matters only at PPO stage. PPO stays
OFF until the autonomous loop demonstrably lives and improves over long sessions.

### Next (user-approved priority)
1. Keep the online agent running; improve navigation so `explore`/targeting
   actually moves the agent toward mobs/NPCs/content.
2. Track behaviour development over LONG sessions (10k+ steps): does the agent
   start accepting quests, completing objectives, recovering from mistakes?
3. PPO becomes a scaling tool ONLY after the autonomous loop is proven alive —
   not a project goal in itself.
