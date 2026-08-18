import json
from wow_env import WoWClassicEnv
from llama_selfplay import summarize_obs, chat, parse_action

env = WoWClassicEnv(player_class="warrior")
obs, info = env.reset(seed=42)
names = env.action_names
n = len(names)
for step in range(5):
    summ = summarize_obs(obs, names)
    prompt = (
        f"STRATEGY: attack safe mobs\n\nOBS: {summ}\n"
        f"ACTION_NAMES: {', '.join(f'{i}:{x}' for i,x in enumerate(names))}\n"
        f"Pick action. Reply ONLY JSON: {{\"action\":<int>,\"reason\":\"<short>\"}}"
    )
    txt = chat("test", prompt, max_tokens=120, temperature=0.3)
    act = parse_action(txt, n)
    print(f"step{step} summ.mobs={summ['mobs']}")
    print(f"  llama_raw={txt[:200]}")
    print(f"  parsed_action={act} ({names[act]})")
    obs, reward, terminated, truncated, info = env.step(act)
    print(f"  reward={reward} kills={info.get('kills')} hp={info.get('hp')}")
    if terminated or truncated:
        obs, info = env.reset(seed=42+step)
env.close()
