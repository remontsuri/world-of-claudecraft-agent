---
name: quest-lifecycle-trace
description: Debug quest objective and lifecycle failures in game agents.
version: 1.0.0
author: WoC
tags: [debugging, quest, lifecycle, game-agent]
---

# Quest Lifecycle Trace

Use when:
- `quest_status=ACTIVE` but objectives never progress
- `targetMobId` in quest doesn't match killed mobs
- Quest giver NPC not found / wrong coordinates
- `accept_quest` or `turn_in_quest` silently fails

## Diagnostic Steps

### 1. Capture Quest State
```python
quest_log = info.get("quest_log", {})
for qid, qp in quest_log.items():
    print(f"{qid}: state={qp.state} objectives={qp.objectives}")
    print(f"  targetMobId={qp.targetMobId}")
    print(f"  turnInNpc={qp.turnInNpc.id} at ({qp.turnInNpc.x}, {qp.turnInNpc.z})")
```

### 2. Verify Mob↔Quest Alignment
- Is `targetMobId` in `nearby` entities?
- Does `targetMobId` have `hostile=true` and `hp>0`?
- After kill, does `dead=true` and `lootable=true`?
- Does killing this mob increment the quest objective counter?

### 3. Common Quest Traps

| Trap | Symptom | Root Cause |
|------|---------|------------|
| Stale targetMobId | Quest points to mob that was killed 100 steps ago | Quest not updated after objective complete |
| Wrong NPC giver | Agent navigates to wrong coordinates | `world_mem` stale vs `giver_positions.json` |
| QuestDb=None | `accept_quest` does nothing silently | Page reload mid-session, game not booted |
| Objective mismatch | Kills=8/8 but quest still shows 0/8 | Wrong mob type (killed wolves, quest wants bears) |

### 4. Resolution Protocol
1. CDP-eval `sim.questLog` and `sim.questDb` before any code change
2. Compare `targetMobId` with actual `nearby` entities
3. Verify NPC coordinates against `giver_positions.json`
4. Check `questDb !== None` (discriminator for quest system readiness)
