"""Debug v6: wander policy, watch for first engage."""
import numpy as np
from wow_env import WoWClassicEnv
import simple_warrior_agent as sw

env = WoWClassicEnv(player_class="warrior", max_steps=5000)
off = sw.resolve_offsets(env.action_names)
a = {name: i for i, name in enumerate(env.action_names)}
a = {
    "eat_drink": a["eat_drink"], "interact": a["interact"], "forward": a["forward"],
    "turn_left": a["turn_left"], "turn_right": a["turn_right"],
    "target_nearest": a["target_nearest"], "attack": a["attack"],
    "ability_1": a["ability_1"], "ability_2": a["ability_2"], "ability_3": a["ability_3"],
}

for seed in (1000, 1001, 1002, 1003, 1004):
    sw._step = 0
    obs, info = env.reset(seed=seed)
    first_engage = None
    for step in range(2000):
        act = sw.policy(obs, off, a)
        obs, reward, term, trunc, info = env.step(act)
        if info.get("kills", 0) > 0 or info.get("deaths", 0) > 0:
            first_engage = (step, info.get("kills"), info.get("deaths"))
            break
        if term or trunc:
            break
    print(f"seed {seed}: first_engage={first_engage} final={info}")
env.close()
