"""Probe: inspect obs nearby-mob slots + sim entity count after movement."""
from wow_env import WoWClassicEnv

env = WoWClassicEnv(player_class="warrior", max_steps=20000, frame_skip=5)
obs, info = env.reset(seed=42)  # seed from their train set
print(f"seed42 start pos={info.get('player_pos')}")

for i in range(300):
    a = 1 if i % 15 != 0 else 4  # forward, sometimes turn_right
    obs, r, term, trunc, info = env.step(a)
    # nearby mobs occupy obs[36:66] (16 self+20 ability + 9 target = 45; then 5 mobs x6=30 -> 45..75)
    # print first mob slot dist (obs[45]) every 50 steps
    if i % 50 == 0:
        mob0_dist = obs[45] if len(obs) > 45 else None
        print(f"  step {i}: mob0_dist_norm={mob0_dist:.2f} target={info.get('targetId')} kills={info.get('kills')} pos={info.get('player_pos')}")
    if info.get("kills", 0) > 0:
        print(f"  KILL at step {i}!")
        break
    if term or trunc:
        break
env.close()
