---
name: agent-stuck-pattern-diagnostics
description: Diagnose farm→loot→navigate stuck loops in game agents.
version: 1.0.0
author: WoC
tags: [debugging, diagnostics, stuck-pattern, game-agent, fsm]
---

# Agent Stuck Pattern Diagnostics

Use when autonomous game agent loops on farm/loot/navigate with:
- `reward/100steps < 0` (negative reward signal)
- `repeated_error_rate > 10%`
- `kills` stall for hundreds of steps
- `quest_status` stays ACTIVE with no objective progress
- `hp` oscillates (death/regen cycle)

## Diagnostic Checklist

### 1. Capture Raw Telemetry Per Step
For ONE full stuck cycle (typically 5-20 steps), capture:
- `snapshot` before action
- `target_mob_id` and its `hp/maxHp/dead/lootable/hostile/x/z`
- `action` selected + `ctx` passed
- `bridge_response` (ok, info, error)
- `snapshot` after action
- `verdict` + `reason`
- `fsm.transition` (old_goal → new_goal)
- `reward` delta

### 2. Common Stuck Patterns

| Pattern | Symptom | Root Cause | Fix |
|---------|---------|------------|-----|
| Dead mob loop | `kills=0`, `dist` frozen, farm→inconclusive | Entity with `hp=0` still in `entities`, `nearest_mob_distance` excludes it but `targetMobId` still points at it | Filter dead mobs from target selection |
| Loot loop | `loot→inconclusive` forever | Mob marked dead but not lootable, or loot action has wrong bridge idx | Check `dead/lootable` flags, verify bridge case |
| Navigate ping-pong | `navigate→INCONCLUSIVE`, `dist` oscillates 30→60→30 | `INTERACT_RANGE` gate, target moves, or pathfinder stuck | Verify distance threshold, check if target is static |
| FSM demote loop | `QUEST_NONE→DO_OBJECTIVE→QUEST_NONE` | Quest objectives never complete, FSM resets | Check `targetMobId` in quest objective vs selected mob |
| Corpse targeting | `farm→success` but `kills=0` | Auto-attack targets corpse, not new mob | Filter `dead=true` from target candidates |

### 3. Forensic Trace Recipe

```python
if i % 1 == 0:
    _t = ws.get("target_mob_id")
    _e = ws["entities"].get(_t, {}) if _t else {}
    print(f"[forensic] step={i} action={a} target={_t} hp={_e.get('hp')} dead={_e.get('dead')} loot={_e.get('lootable')} verdict={verdict}", flush=True)
```

### 4. Resolution Protocol

1. Stop the agent before editing code
2. Kill stale processes
3. Clear `__pycache__`
4. Apply minimal fix (one change per commit)
5. Add regression test
6. Verify with 100-step live smoke

### 5. Known WoC-Specific Traps

- `world_state.py` filters `dead` mobs from `nearest_mob_distance` but NOT from `targetMobId` selection
- `has_corpse` considers `dead && lootable` as valid target (correct for loot, wrong for farm)
- Bridge `case 0` (farm) does NOT validate target is alive before attacking
- `FSM.decide()` may override `farm` with `explore` even when mobs are in range
