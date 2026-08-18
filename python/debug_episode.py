import sys, time
from wow_env import WoWClassicEnv
from llama_selfplay import play_episode, BASE_STRATEGY

env = WoWClassicEnv(player_class="warrior")
t0 = time.time()
print("START episode", flush=True)
res = play_episode(env, BASE_STRATEGY, 20, 0)
print("RESULT", res, "elapsed", round(time.time()-t0, 1), flush=True)
env.close()
