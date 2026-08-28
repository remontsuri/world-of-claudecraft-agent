# WoC-Ragent — Project Memory

> **CANONICAL HANDOFF.** Read this file before making any code change.
> Last verified: 2026-08-28.
> Agent repo: `remontsuri/world-of-claudecraft-agent`, branch `backup`.
> Game source repo: `levy-street/world-of-claudecraft`.

## 0. Non-negotiable rule

Do not invent game behavior. The game repository and the live offline client are the source of truth for game APIs, entity schemas, ranges, item IDs, quest states and runtime behavior.

Do not create a second architecture. Before changing code read:
1. `memory.md`
2. `docs/ARCHITECTURE-CONSENSUS.md`
3. `docs/ARCHITECTURE.md`
4. `docs/AGENT-OPERATING-CONTRACT.md`
5. the latest commits

Required workflow: **READ → REPRODUCE → RED TEST → MINIMAL FIX → FULL TEST → LIVE PROBE → COMMIT**.

## 1. Current repository state

Latest known commit before the handoff cleanup: `c1224c30` (bridge jump + stuck detection). During this handoff the following documentation/config commits were added:
- `ad755ecb` — binding Agent Operating Contract
- `2b5c26f7` — ignore regenerable runtime/replay state
- this memory update

The current default branch is `backup`.

## 2. Two repositories / ownership

### GAME — `levy-street/world-of-claudecraft`
Owns:
- `Sim`
- actual game entities and content
- quest APIs and quest state
- item definitions
- combat rules
- movement/controller
- offline runtime

### AGENT — `remontsuri/world-of-claudecraft-agent`
Owns:
- browser bridge
- canonical WorldState adapter
- observation
- contracts and action masks
- planner / GoalFSM
- policy / Q-learning
- PPO integration when explicitly used by an RL runner
- navigation controller
- recovery / anti-loop
- memory / replay / reflection
- tests and telemetry

Never alter GAME to hide an AGENT defect unless explicitly requested.

## 3. Target runtime

Primary integration target: **offline browser client**.

Typical stack:
- Vite game: `localhost:5173`
- Chrome CDP: `127.0.0.1:9222`
- agent bridge: `:8791`
- bridge file: `browser_bridge.cjs`

Offline launch flow is not the old online Play flow. Use the repository's offline launcher/entry script and ensure `window.__game.sim` exists before declaring the game ready.

Health must show:
`ok=true, bridge=true, page=true, game=true`.

## 4. Canonical pipeline

```text
GAME SIM
  ↓
browser_bridge.cjs
  ↓
canonical WorldState
  ↓
Observation
  ↓
GoalFSM / Planner context
  ↓
Policy / Q / PPO (only in runners that actually instantiate PPO)
  ↓
Skill
  ↓
Contract + verifier
  ↓
bridge/game API
  ↓
GAME SIM
```

Single responsibility:
- Sim = actual truth
- bridge = transport + exact game API calls
- WorldState = canonical facts
- Observation = agent representation
- GoalFSM = durable goal owner
- Planner = current subgoal
- Policy/Q/PPO = action choice within allowed space
- Contracts = executability
- NavigationController = movement toward target
- Skill = one capability
- Recovery = response to failure/stuck
- Memory/Replay = learning state, never live-world authority
- SelfReflection/LLM = advisory unless an explicit architecture change grants a different role

## 5. Navigation

There is **one** navigation implementation: `python/navigation.py::NavigationController`.

Current valid low-level skill set remains fixed to the game's/hierarchical environment mapping. `explore` is the transport action used to execute navigation because there is no separate navigation skill index. Do not invent `navigate_to_giver` as a new low-level skill index.

Semantic navigation intents may be represented above the skill layer:
- GO_TO_GIVER
- GO_TO_VENDOR
- GO_TO_NODE
- FIND_MOB
- EXPLORE
- UNSTUCK

All must use the same NavigationController / bridge movement path.

Do not add another walker, anchor driver, direct coordinate writer, or competing movement loop. While autonomy is active, WorkAnchor is observation-only.

Navigation substeps are not learning transitions unless they pass through the actual learning chain. Count them separately.

## 6. Goal ownership

`GoalFSM` is the durable single writer of the current goal.

LLM/brain may call `suggest()` / provide advisory information but must not silently replace the FSM goal. Planner chooses a subgoal from the observed goal; it does not directly mutate the game.

If a future change introduces another goal writer, stop and add an explicit architecture decision + regression test first.

## 7. Logistics vs learning

Basic logistics must be deterministic and truthful rather than discovered from Q:
- accept quest
- navigate to giver
- return to giver
- turn in quest
- navigate to vendor
- sell junk
- buy required tool
- navigate to gather node

Q-learning/PPO is appropriate for combat and micro-decisions. Do not use learning to compensate for a missing state field, bad verifier or missing navigation edge.

## 8. Verified game contracts — do not re-invent

These facts were checked against the game/live client:

- `acceptQuest` works offline when the quest giver is inside the interaction range; too-far is an honest game failure.
- `questState()` is authoritative for offline quest availability.
- `sim.questsDone` is authoritative for completed quests in offline. Do not read only `g.online.questsDone`.
- NPCs may exist in `worldContent.npcs` but not be runtime interaction entities; interaction requires the actual runtime target/range.
- inventory canonical IDs use `itemId`; normalize to `inventory_by_id` / `inv_by_id` consistently.
- item `quality` is a string (`poor`, `common`, `uncommon`, `rare`, `epic`), not numeric zero.
- loot requires an actual dead mob/corpse. `lootable:true` alone is unsafe because world decoration can also be lootable.
- verified gather tools include `handaxe`, `gathering_sickle`, `copper_mining_pick`.
- `logging_axe` and `herb_sack` were observed as invented/nonexistent names and must not return to code.
- `respawn` is an endpoint, not a skill index.
- player position is server-authoritative; direct `p.pos` assignment is not a movement mechanism.
- combat requires target acquisition plus the game's auto-attack/facing/range rules; the real combat smoke has already been confirmed.

## 9. Fixed defects already verified

Do not redo these as speculative fixes:

- junk detection unified through real string quality semantics
- ExperienceStore no longer saves on every update
- hot-path trace file opens removed/gated
- autonomy startup fails closed instead of silently disabling itself
- navigation substeps are counted separately
- canonical inventory aliases are synchronized
- canonical WorldState → Observation preserves entities, corpses, gather nodes, vendors, quest givers, objectives, level and mana
- NPC registry has source priority and canonical `npc_id`
- quest availability uses authoritative quest states
- GO_TO_GIVER is represented as navigation intent executed through `explore`, not an unknown skill
- loot rejects scenery
- heal is not offered when there is no real healing item
- policy receives autonomy candidate masking
- bridge has jump/stuck handling

Evidence lives in the corresponding commits and regression tests; the current files are the final authority.

## 10. V0 baseline — immutable

`docs/baselines/V0-browser-2026-08-27.md` is frozen.

Measured:
- 989 environment/learning steps
- ~0.13 browser steps/sec
- AutonomyScore 30.2%
- NO_OP 979 / 989 (99.0%)
- FAILURE 5
- SUCCESS 5

The agent completed a real quest cycle in the first 35 steps, then spent 964 steps on `accept_quest -> NO_OP`.

Important correction: the quest **was actually turned in**. Offline `sim.questsDone` contained `q_wolves`; the snapshot's online-only `quests_done` field was wrong. Never use the legacy snapshot as authority for this fact.

V0 is evidence, not a target to preserve. Never edit it retroactively.

## 11. PPO status

The browser autonomous runner is currently a tabular Q/ExperienceStore policy path unless the runner explicitly constructs a PPO policy.

The headless/env-server RL stack can use PPO and is useful for high-speed training experiments. Headless and browser metrics answer different questions and must not be mixed.

Do not claim “PPO controls the browser agent” without tracing the actual runtime call path and showing PPO initialization + inference.

## 12. Current architecture risk to fix before long runs

The current code has a good NavigationController and a GoalFSM, but the semantic decision path must remain clean:

```text
Planner/Goal context
       ↓
Autonomy decision context
       ↓
Policy chooses among allowed skills
       ↓
Skill execution
```

Avoid using mutable `policy.hints` as a hidden command bus. `masked_candidates` and forced decisions should eventually become explicit decision-context fields. Do not perform a broad refactor during a baseline run; add a RED regression first.

`explore` must remain a transport action, not a pile of unrelated policy meanings.

## 13. Long-horizon acceptance target

The architecture consensus target for a genuinely autonomous run is:
- ≥10 quests completed per 5000 steps
- turn-in success ≥90%
- deaths ≤2/1000 steps
- `P(heal | hp<0.35) ≥0.70`
- second half of a 10000-step run ≥1.25× quests and ≤0.7× deaths versus first half
- zero blocking LLM calls in `decide()`; periodic advisory calls only

These are acceptance targets, not claims that the current agent meets them.

## 14. Runtime memory policy

Runtime artifacts are **regenerable** and should not grow Git history:
- `experience_autonomous.json`
- `replay_buffer.json`
- autonomous/step/crash/lifecycle logs
- PID/lock files
- goal/self-reflection/world/strategy runtime state

They are now ignored by `.gitignore`. Keep compact aggregate baseline reports under `docs/` instead.

Do not commit a new multi-megabyte replay just to “remember” a run. Record the run's metrics, seed/start state, code SHA and conclusions.

## 15. Hermes handoff checklist

At the beginning of every fresh coding session:

1. `git status` / current HEAD
2. read this file
3. read `docs/AGENT-OPERATING-CONTRACT.md`
4. read `docs/ARCHITECTURE-CONSENSUS.md`
5. inspect the latest 10 commits
6. inspect relevant current files, not old chat claims
7. run full pytest before declaring the tree green
8. for game behavior, verify against the main game repo or live CDP
9. make one minimal change
10. add/adjust regression test
11. run full tests
12. live-probe only after tests pass
13. commit and push

Never say “fixed” from a tool-call narrative alone. The evidence is:
**current file + regression test + test result + live measurement + commit SHA**.
