import json
from wow_env import WoWClassicEnv

env = WoWClassicEnv(player_class="warrior")
obs, info = env.reset(seed=42)
print("OBS_LEN", len(obs))
print("OBS", json.dumps([round(float(x),3) for x in obs]))
print("INFO", json.dumps(info, default=str)[:500])
print("ACTION_NAMES", env.action_names[:12])
# show nonzero indices
nz = [(i, round(float(obs[i]),3)) for i in range(len(obs)) if abs(obs[i])>0.001]
print("NONZERO", nz[:60])
env.close()
