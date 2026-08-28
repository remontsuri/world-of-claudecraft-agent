# Agent Operating Contract — WoC Autonomous Agent

**Status:** BINDING
**Updated:** 2026-08-28
**Purpose:** prevent context loss and stop future coding agents from inventing a second architecture or repeating already-verified fixes.

## 1. Source of truth

There are two repositories and they have different ownership:

- `levy-street/world-of-claudecraft` = GAME. Its `Sim`, content, APIs and runtime behavior are authoritative for what the game actually does.
- `remontsuri/world-of-claudecraft-agent` = AGENT. Python autonomy, policy, memory, planner, contracts, browser bridge and tests live here.

Never infer a game contract from the agent repository when the game source can be inspected. Never modify the game repository to compensate for an agent bug unless the user explicitly asks for a game change.

Offline browser mode is the primary real-client integration target. Headless/env-server is a separate high-speed RL environment using the same game core; its metrics must never be presented as browser autonomy metrics.

## 2. One pipeline

```text
GAME SIM
  -> browser_bridge.cjs
  -> canonical WorldState
  -> Observation
  -> Goal/Planner context
  -> Policy / Q / PPO (when the selected runner uses PPO)
  -> Skill
  -> Skill Contract + verifier
  -> bridge action
  -> GAME SIM
```

Each layer has one job:

| Layer | Sole responsibility |
|---|---|
| Sim | actual game state and rules |
| bridge | transport + exact game API calls |
| WorldState | canonical representation of observed facts |
| Observation | agent-facing encoding; must not invent facts |
| GoalFSM/Planner | current objective/subgoal |
| Policy/Q/PPO | choose among permitted skills / combat decisions |
| Contracts | whether a skill is currently executable |
| NavigationController | movement toward a concrete target |
| Skill | execute one capability |
| Recovery | react to failure/stuck and select a new strategy |
| Memory/Replay | learning state, never authority over live world facts |
| SelfReflection | produce advisory lessons, never silently rewrite goals |

If two components answer the same question, stop and reconcile ownership before adding another heuristic.

## 3. Navigation rule

There is exactly one navigation implementation: `python/navigation.py::NavigationController`.

`explore` is a valid low-level skill used as the transport action for navigation because the skill index is fixed. It is **not** a synonym for every kind of intent. The semantic intent must come from the Planner/Autonomy context (`GO_TO_GIVER`, `GO_TO_VENDOR`, `GO_TO_NODE`, `FIND_MOB`, `EXPLORE`, etc.).

Do not create another walker, anchor driver, direct coordinate writer, or parallel navigation implementation. `controller.move` / bridge navigation is authoritative. Direct writes to player position are not persistent in the game.

Navigation legs are not learning transitions unless they pass through the actual learning path. Do not count navigation substeps as environment learning steps.

## 4. Goal ownership

`GoalFSM` is the single writer of the durable current goal.

LLM/brain/self-reflection may suggest a goal or provide advisory information. They must not silently overwrite the FSM state. A new goal writer requires an explicit architecture change and regression tests.

The Planner describes the next subgoal; it does not directly execute game actions.

## 5. Logistics vs learning

The following are deterministic logistics capabilities and must not depend on Q-learning to discover basic game mechanics:

- accept quest
- navigate to giver
- return to giver
- turn in quest
- navigate to vendor
- sell junk
- buy required tool
- navigate to gather node

Q-learning/PPO is valuable for combat and micro-decisions. It must not be used as a substitute for a missing state/contract/navigation edge.

## 6. Game contracts already verified

Do not re-fix these without a new contradictory live measurement:

- `acceptQuest` works in offline when the giver is within the interaction range; when the giver is too far it fails honestly.
- `sim.acceptQuest()` depends on an NPC entity/position being reachable; worldContent alone is not an interaction target.
- `questState()` is authoritative for offline quest availability.
- `sim.questsDone` is the authoritative offline completed-quest state; do not read only `g.online.questsDone`.
- inventory uses canonical `itemId` and `inventory_by_id` / `inv_by_id` normalization.
- item `quality` is a string such as `poor`, `common`, `uncommon`, `rare`, `epic`.
- loot targets must be actual dead mobs/corpses; `lootable:true` alone is not enough because scenery can be lootable.
- real gather tools include `handaxe`, `gathering_sickle`, `copper_mining_pick`; do not invent `logging_axe` or `herb_sack`.
- `respawn` is an endpoint, not a skill index.
- skill indices must remain aligned with `hierarchical_env.SKILLS` and bridge dispatch.
- server-authoritative player position must be changed through game movement/controller, not by assigning `p.pos`.

## 7. Baseline discipline

`V0` is frozen. Never modify its source data or retroactively rewrite its conclusions.

Before a long run:

1. inspect the current HEAD and recent commits;
2. run the full Python test suite, not a selected subset;
3. verify bridge/game health;
4. record the exact starting state;
5. do a read-only live probe when a game contract is uncertain;
6. freeze code during the measurement;
7. separate environment steps, learning steps and navigation substeps;
8. rank failures by lost progress, not by raw exception count.

A green test suite proves the test contracts. It does not prove long-horizon autonomy.

## 8. Self-learning boundary

The current browser runner uses the tabular ExperienceStore/Q policy. The separate headless RL stack can use PPO. Do not claim PPO is controlling the browser runner unless the code path demonstrably instantiates and executes a PPO policy.

Learning must consume truthful transitions:

```text
before state -> skill -> actual game effect -> after state -> verifier -> reward -> memory
```

A false snapshot field poisons both verification and learning. Canonical state therefore has priority over convenience fields supplied by the bridge.

## 9. Fail-closed rules

- Unknown predicate -> fail closed.
- Unknown skill -> never silently execute it.
- `ok:false` from bridge -> never convert to success.
- Missing state -> do not invent a positive fact.
- Navigation without a target -> use explicit exploration/search behavior, not a fake arrival.
- Recovery must alter future behavior; logging a recovery action without executing or changing state is not recovery.
- A metric must not count an action as successful unless the postcondition was actually observed.

## 10. Required workflow for every future fix

```text
READ -> REPRODUCE -> RED TEST -> MINIMAL FIX -> FULL TEST -> LIVE PROBE -> COMMIT
```

Never start with a speculative rewrite.

When a defect is found, document:

- exact source-of-truth field/API;
- observed bad behavior;
- minimal root cause;
- regression test;
- live verification result;
- commit SHA.

## 11. Hermes handoff

If another coding session is started, its first action is to read:

1. `memory.md`
2. `docs/ARCHITECTURE-CONSENSUS.md`
3. `docs/ARCHITECTURE.md`
4. this file
5. the latest 10 commits

Then inspect the actual code before changing anything.

The sentence "already fixed" is not evidence; the commit and current file are evidence.
The sentence "I ran tests" is not enough; state the exact suite and result.
The sentence "live works" is not enough; state the exact probe and observed state transition.
