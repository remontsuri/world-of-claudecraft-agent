---
name: fsm-state-trace
description: Trace FSM transition loops in autonomous game agents.
version: 1.0.0
author: WoC
tags: [debugging, fsm, state-machine, game-agent]
---

# FSM State Trace

Use when:
- Agent loops through FSM states without terminal progress (e.g. `NO_QUEST→FIND→ACCEPT→FAIL→NO_QUEST`)
- `quest_status` demotes repeatedly
- FSM overrides policy decisions (forced heal/return/explore)

## Diagnostic Steps

### 1. Map the State Machine
Dump all FSM states and transitions:
```bash
grep -n "def .*->\|FSM\.\|goal.*=" path/to/goal_fsm.py | head -40
```

### 2. Capture Transition Log
For each step, log:
- `fsm.goal` BEFORE decision
- `action` selected by policy
- `verdict` + `outcome_kind`
- `fsm.goal` AFTER transition
- Is this a `promote`, `demote`, or `lateral` move?

### 3. Common FSM Traps

| Trap | Symptom | Root Cause |
|------|---------|------------|
| Demote on inconclusive | `farm→inconclusive` causes `DO_OBJECTIVE→NO_QUEST` | FSM treats inconclusive as objective failure |
| Heal override loop | FSM forces `heal` even at hp=0.8 | Heal precondition broken (was `in_combat` failure_reason) |
| Forced explore blindness | FSM overrides `farm` with `explore` when mobs in range | `pending_recovery` gate in `before_action` |
| Dead branch trap | FSM method has correct logic but nothing calls it | Verify `Agent._cycle()` calls the method |

### 4. Resolution Protocol
1. Log the full transition sequence
2. Identify the FIRST transition that breaks the expected path
3. Check whether the method is actually called (dead branch)
4. Verify preconditions are not masking the correct transition
5. Add unit test for the specific transition
