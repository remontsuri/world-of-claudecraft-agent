"""Smoke test for the WoC RL integration (no game/bridge needed).

Proves the 4 things claimed "missing" actually now WORK after wiring:
  1. GoalFSM drives current_goal from observed world + persists goal_state.json
  2. world_state builds structured quest{phase,progress,required,giver_distance}
  3. ReplayBuffer stores + trains (rare-event priority)
  4. StrategyMemory records per-(quest,skill) outcomes

Run: python -u _smoke_integration.py
"""
import os
import json
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from world_state import build_world_state
from goal_fsm import GoalFSM
from replay_buffer import ReplayBuffer
from strategy_memory import StrategyMemory
from memory import ExperienceStore, _bucket
from policy import GoalManager


def fake_info(quest=None):
    """Minimal env info dict for build_world_state."""
    info = {
        "player": {"hp": 100, "maxHp": 100, "dead": False},
        "player_pos": [0, 0],
        "nearby": [],
        "inventory": [],
        "quests": {"active": [], "ready": [], "done": []},
        "kills": 0, "xp": 0, "copper": 0, "quests_done": 0, "deaths": 0,
        "in_combat": False,
    }
    if quest == "active":
        info["quests"]["active"] = [{
            "id": "q_bones", "state": "active",
            "turnInNpc": {"id": "npc_42", "x": 50, "z": 20},
            "objectives": [{"current": 3, "required": 8}],
        }]
    elif quest == "ready":
        info["quests"]["active"] = [{
            "id": "q_bones", "state": "ready",
            "turnInNpc": {"id": "npc_42", "x": 50, "z": 20},
            "objectives": [{"current": 8, "required": 8}],
        }]
    elif quest == "none":
        pass
    return info


ok = []
def check(name, cond, detail=""):
    ok.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# ---- 1. world_state structured quest ----
ws_none = build_world_state(fake_info("none"))
ws_act = build_world_state(fake_info("active"))
ws_rdy = build_world_state(fake_info("ready"))
check("world_state.quest structured (none)", isinstance(ws_none.get("quest"), dict))
check("world_state.quest ACTIVE progress=3/8",
      ws_act["quest"]["progress"] == 3 and ws_act["quest"]["required"] == 8
      and ws_act["quest"]["phase"] == "ACTIVE")
check("world_state.quest READY complete=True",
      ws_rdy["quest"]["complete"] is True and ws_rdy["quest"]["phase"] == "READY")
check("world_state.quest giver_distance is a number",
      isinstance(ws_act["quest"]["giver_distance"], float))


# ---- 2. GoalFSM sync + persist ----
fsm = GoalFSM(path=os.path.join(HERE, "_smoke_goal_state.json"))
fsm.reset_to_no_quest()
fsm.update_from_world(ws_none)
check("FSM NO_QUEST when no quest", fsm.goal == "NO_QUEST", f"goal={fsm.goal}")
fsm.update_from_world(ws_act)
check("FSM DO_OBJECTIVE on active", fsm.goal == "DO_OBJECTIVE", f"goal={fsm.goal}")
fsm.update_from_world(ws_rdy)
check("FSM TURN_IN on ready", fsm.goal == "TURN_IN", f"goal={fsm.goal}")
# death preserves pre-death goal
fsm.enter_dead()
check("FSM DEAD after enter_dead", fsm.goal == "DEAD")
fsm.resume_after_respawn()
check("FSM resumes pre-death goal (TURN_IN)", fsm.goal == "TURN_IN", f"goal={fsm.goal}")
fsm.save()
with open(fsm.path) as f:
    gd = json.load(f)
check("goal_state.json persisted", gd["goal"] == "TURN_IN")
os.unlink(fsm.path)


# ---- 3. ReplayBuffer + training ----
mem = ExperienceStore(path=os.path.join(HERE, "_smoke_exp.json"))
rb = ReplayBuffer(path=os.path.join(HERE, "_smoke_rb.json"), cap=1000)
# 5 rare turn_in successes + 50 common explore steps
# NOTE: replay items store the RAW WorldState dict (as play_autonomous.py does),
# so update() can bucketize them. We reuse build_world_state outputs.
ws_explore = build_world_state(fake_info("none"))
ws_ready = build_world_state(fake_info("ready"))
for _ in range(50):
    rb.add({"state": ws_explore,
            "action": "explore", "reward": 0.0,
            "next_state": ws_explore,
            "done": False, "goal": "NO_QUEST", "skill": "explore", "event": None})
for _ in range(5):
    rb.add({"state": ws_ready,
            "action": "turn_in_quest", "reward": 10.0,
            "next_state": ws_explore,
            "done": False, "goal": "TURN_IN", "skill": "turn_in_quest",
            "event": "QUEST_TURNIN_SUCCESS"})
check("ReplayBuffer stored 55", len(rb) == 55, f"len={len(rb)}")
batch = rb.sample(32)
# rare events should dominate the sample
rare = sum(1 for b in batch if b.get("event") == "QUEST_TURNIN_SUCCESS")
check("ReplayBuffer rare-event priority (>=5/32 rare)",
      rare >= 5, f"rare_in_batch={rare}")
trained = mem.train_from_replay(rb, batch=64)
check("train_from_replay applied updates", trained > 0, f"trained={trained}")
# the rare event's value should be positive (reward +10)
val = mem.value("hp=full|qs=READY_TO_TURN_IN|mob=0|corpse=0|junk=0|danger=0|far=0|combat=0",
                "turn_in_quest")
check("rare-event Q learned positive", val > 0, f"Q(turn_in|ready)={val:.2f}")
for p in (rb.path, mem.path):
    try:
        os.unlink(p)
    except OSError:
        pass

# ---- 4. StrategyMemory ----
sm = StrategyMemory(path=os.path.join(HERE, "_smoke_strat.json"))
sm.record_outcome("quest:q_bones", "farm", success=True)
sm.record_outcome("quest:q_bones", "farm", success=True)
sm.record_outcome("quest:q_bones", "explore", success=False)
pref = sm.preference("quest:q_bones")
check("StrategyMemory prefers farm", pref == "farm", f"pref={pref}")
os.unlink(sm.path)


# ---- 5. policy.decide phase gate ----
pmem = ExperienceStore(path=os.path.join(HERE, "_smoke_pol.json"))
gm = GoalManager(pmem, temperature=0.001, seed=1)
# with goal=RETURN_TO_GIVER, decide must NOT offer explore/farm
ws = build_world_state(fake_info("ready"))
a, ctx = gm.decide(fake_info("ready"), ws=ws, goal="RETURN_TO_GIVER")
check("phase gate: RETURN_TO_GIVER -> only return/turn_in",
      a in ("return_to_giver", "turn_in_quest"), f"action={a}")
# with goal=DO_OBJECTIVE, decide must NOT offer explore/turn_in
ws2 = build_world_state(fake_info("active"))
a2, _ = gm.decide(fake_info("active"), ws=ws2, goal="DO_OBJECTIVE")
check("phase gate: DO_OBJECTIVE -> only farm/loot/gather",
      a2 in ("farm", "loot", "gather"), f"action={a2}")
# cleanup (files may not exist if save() was never triggered)
for p in (rb.path, mem.path, pmem.path, sm.path):
    try:
        os.unlink(p)
    except OSError:
        pass


print("\n=== %d/%d checks passed ===" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
