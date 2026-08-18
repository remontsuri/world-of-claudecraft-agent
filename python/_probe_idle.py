"""Probe: stand still at spawn, do idle ticks spawn mobs nearby?"""
from wow_env import WoWClassicEnv

env = WoWClassicEnv(player_class="warrior", max_steps=20000, frame_skip=5)
obs, info = env.reset(seed=42)
print(f"spawn pos={info.get('player_pos')}")
for i in range(400):
    obs, r, term, trunc, info = env.step(0)  # noop, let idle ticks run
    if i % 50 == 0:
        mob0 = obs[45] if len(obs) > 45 else None
        print(f"  step {i}: mob0_dist={mob0:.2f} target={info.get('targetId')} kills={info.get('kills')}")
    if info.get("kills", 0) > 0:
        print(f"  KILL at {i}")
        break
    if term or trunc:
        break
env.close()
