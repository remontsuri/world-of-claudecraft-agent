import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from browser_env import BrowserEnv
from agent import Agent
from memory import ExperienceStore, _bucket
from world_state import build_world_state

EXP = os.path.join(os.path.dirname(__file__), "experience_autonomous.json")
mem = ExperienceStore(path=EXP)
env = BrowserEnv(player_class="warrior", max_steps=100000, seed=123)
env.reset(seed=123)
agent = Agent(env, mem, seed=999)

# force respawn if dead/low
info = env._last_info
if (info.get("player", {}).get("hp", 1) or 1) <= 0:
    env.respawn()
    info = env._last_info

print("start pos:", info.get("player_pos"), "hp:", info.get("player", {}).get("hp"))
print("start bucket:", _bucket(build_world_state(info)))

neg = 0
for i in range(30):
    rec = agent.step()
    bk = _bucket(rec["ws_before"])
    info = env._last_info
    if rec["ws_after"].get("hp_frac", 1) <= 0 or rec["ws_after"].get("deaths", 0) > 0:
        env.respawn()
    if rec["reward"] < -0.1:
        neg += 1
    print(f"[{i}] act={rec['action']:14s} r={rec['reward']:+.2f} "
          f"bucket={bk} pos={info.get('player_pos')} "
          f"hp={(info.get('player') or {}).get('hp')}")
print("NEGATIVE steps:", neg)
