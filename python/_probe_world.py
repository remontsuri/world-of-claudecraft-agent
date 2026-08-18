"""Probe: what entities exist after headless reset? Is the world populated?"""
from wow_env import WoWClassicEnv

env = WoWClassicEnv(player_class="warrior", max_steps=5000, frame_skip=5)
obs, info = env.reset(seed=7)
# peek into sim via the env's internal reference if exposed; else use info
print("info keys:", list(info.keys()))
print("player_pos:", info.get("player_pos"))
print("level:", info.get("level"), "kills:", info.get("kills"), "quests_done:", info.get("quests_done"))

# step a few noops and see if mobs appear in obs (nearby mobs section)
for i in range(5):
    obs, r, term, trunc, info = env.step(0)
print("obs len:", len(obs))
# nearby mobs occupy indices 16+ABILITY_SLOTS*2 .. +30 (5 mobs x6). Print first 60 obs values
print("obs[0:60]:", [round(x, 2) for x in obs[:60]])
env.close()
