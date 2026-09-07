# Forensic Trace: Stuck Pattern Session 2026-09-07

## Raw Telemetry (last 500 steps of 1504-step run)

```
reward/100steps = -8.68
death/100steps  = 1.60
repeated_error_rate = 40.80%
action_dist = {'loot': '26.6%', 'farm': '22.6%', 'navigate': '44.6%', 'return_to_giver': '3.6%', 'explore': '2.6%'}
kills=5, deaths=8, level=1
```

## CDP Probe (live game state)

```json
{
  "player": {
    "pos": [11.75, -24.82],
    "hp": 0,
    "maxHp": 100,
    "level": 1,
    "dead": true,
    "facing": 1.284,
    "inCombat": false
  },
  "questDb": "MISSING",
  "quests": {
    "q_wolves": {
      "state": "active",
      "targetMobId": null,
      "objectives": []
    }
  },
  "nearbyMobs": [],
  "nearbyCount": 0
}
```

## Root Cause Chain

### 1. QuestDb=None Trap (Primary)
After respawn, `sim.questDb` is `None` (not a Map). The game's quest system is broken.
- `acceptQuest()` silently returns `None`
- `questLog` still shows `q_wolves` with `state=active` but empty `objectives`
- `targetMobId=null` — no valid target for farm

### 2. Empty Nearby Desync
`nearbyCount=0` but FSM still tries `farm` because `has_mob` may be cached from previous step.

### 3. FSM Demote Loop
```
DO_OBJECTIVE → farm→inconclusive → has_mob=False → explore
→ navigate→INCONCLUSIVE → return_to_giver→INCONCLUSIVE
→ QUEST_NONE → DO_OBJECTIVE (qs=ACTIVE) → loop
```

### 4. Death Loop
Agent dies → respawn → questDb not restored → farm fails → death penalty → repeat

## Code Locations

| File | Line | Issue |
|------|------|-------|
| `agent.py` | 471 | `if self.env._last_info.get("player", {}).get("dead")` — checks death but NOT questDb |
| `goal_fsm.py` | 15506 | `_handle_do_objective` returns `"farm"` if `has_mob=True`, doesn't verify questDb |
| `world_state.py` | 347 | `qcomplete` check requires `bool(q.get("objectives"))` — empty objectives = ACTIVE |
| `world_state.py` | 354 | `quest_status="ACTIVE"` when objectives empty — correct but FSM doesn't handle it |

## Minimal Fix Required

1. **agent.py:471** — After respawn, check `sim.questDb !== None` via CDP. If missing, return `ENV_ERROR` and trigger page reload.
2. **goal_fsm.py:_handle_do_objective** — If `nearbyCount=0` and `quest_status=ACTIVE` with empty objectives, return `"explore"` (not `"farm"`)
3. **world_state.py** — Add `quest_db_ready: bool` field to world state, set `has_mob=False` if `quest_db_ready=False`

## Verification

After fix:
- 100-step smoke should show `kills > 0` or `quest_status` progression
- `repeated_error_rate < 5%`
- `reward/100steps > 0`
