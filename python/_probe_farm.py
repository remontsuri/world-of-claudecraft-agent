"""Probe: do mobs appear if the player moves around in headless Sim?"""
from wow_env import WoWClassicEnv

env = WoWClassicEnv(player_class="warrior", max_steps=20000, frame_skip=5)
obs, info = env.reset(seed=7)
print(f"start pos={info.get('player_pos')} kills={info.get('kills')}")

kills_seen = 0
target_seen = False
for i in range(200):
    # move forward + occasionally turn to explore
    a = 1 if i % 20 != 0 else 3  # forward, sometimes turn_left
    obs, r, term, trunc, info = env.step(a)
    if info.get("targetId") is not None:
        target_seen = True
    if info.get("kills", 0) > kills_seen:
        kills_seen = info["kills"]
        print(f"  step {i}: KILL! total kills={kills_seen}, pos={info.get('player_pos')}")
    if term or trunc:
        obs, info = env.reset(seed=7)
        break

print(f"final: target_seen={target_seen} kills={kills_seen} pos={info.get('player_pos')}")
env.close()
