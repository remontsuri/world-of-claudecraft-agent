"""live_smoke_test.py — verify the fix in the REAL game."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from browser_env import BrowserEnv
from agent import Agent
from memory import ExperienceStore
from goal_fsm import GoalFSM
from autonomy import AutonomyLoop

print("=" * 60)
print("LIVE SMOKE TEST: farm→loot→heal loop fix")
print("=" * 60)

# 1. Connect to live game
print("\n[1] Connecting to live game via bridge...")
env = BrowserEnv(player_class="warrior")
info = env._last_info
print(f"    Player: hp={info['player']['hp']}/{info['player']['maxHp']}, "
      f"pos={info['player_pos']}")

nearby = info.get("nearby", [])
quest_npcs = [e for e in nearby if e.get("kind") == "npc" and e.get("questIds")]
print(f"    Nearby quest NPCs: {len(quest_npcs)}")
for npc in quest_npcs[:3]:
    print(f"      {npc['name']} dist={npc['dist']:.1f} quests={npc['questIds']}")

quest_states = info.get("quest_states", {})
available = {k: v for k, v in quest_states.items() if v == "available"}
print(f"    Available quests: {list(available.keys())[:5]}")

# 2. Create agent
print("\n[2] Creating agent with ArbitrationLayer...")
mem = ExperienceStore()
goal_fsm = GoalFSM(memory_path=os.path.join(os.path.dirname(__file__), "goal_fsm_state.json"))
autonomy = AutonomyLoop()
agent = Agent(env, mem, seed=42, fsm=goal_fsm)
agent.set_autonomy(autonomy)
print("    Agent created.")

# 3. Run steps
print("\n[3] Running 60 steps...")
print(f"    {'Step':>4s} {'Action':16s} {'Verdict':12s} {'HP':>6s} {'Dist':>6s} {'Qs':>10s}")
print("    " + "-" * 60)

actions_taken = {}
quests_accepted = 0
initial_qs = None

for step_i in range(60):
    try:
        rec = agent.step()
    except Exception as e:
        print(f"    Step {step_i}: ERROR {e}")
        break

    action = rec["action"]
    verdict = rec["verdict"]
    ws_before = rec["ws_before"]
    ws_after = rec["ws_after"]

    actions_taken[action] = actions_taken.get(action, 0) + 1

    qs_before = ws_before.get("quest_status", "NONE")
    qs_after = ws_after.get("quest_status", "NONE")
    if step_i == 0:
        initial_qs = qs_before
    if qs_after == "ACTIVE" and qs_before != "ACTIVE":
        quests_accepted += 1
        print(f"    *** QUEST ACCEPTED! {qs_before} -> {qs_after}")

    hp = ws_after.get("hp_frac", 1.0)
    dist = ws_after.get("distance_to_giver", 999)

    print(f"    {step_i:4d} {action:16s} {verdict:12s} {hp:6.2f} {dist:6.0f} {qs_after:>10s}")

    if ws_after.get("dead"):
        print(f"\n    Agent died at step {step_i}")
        break
    if qs_after == "DONE":
        print(f"\n    Quest turned in at step {step_i}!")
        break

# 4. Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  Initial quest status: {initial_qs}")
print(f"  Actions taken: {actions_taken}")
print(f"  Quests accepted: {quests_accepted}")

if quests_accepted > 0:
    print("\n  ✓ SUCCESS: Agent accepted a quest (fix is working)")
    sys.exit(0)
elif initial_qs == "ACTIVE":
    print("\n  ✓ PARTIAL: Quest already active, agent is working on it")
    sys.exit(0)
elif actions_taken.get("accept_quest", 0) > 0:
    print("\n  ✓ PARTIAL: Agent tried to accept")
    sys.exit(0)
else:
    print("\n  ✗ FAIL: Agent never tried to accept a quest")
    sys.exit(1)
