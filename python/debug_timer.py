import sys, time
from wow_env import WoWClassicEnv
from llama_selfplay import play_episode, BASE_STRATEGY, summarize_obs, chat, parse_action

env = WoWClassicEnv(player_class="warrior")
obs, info = env.reset(seed=42)
names = env.action_names
n = len(names)
for step in range(40):
    t0 = time.time()
    summ = summarize_obs(obs, names)
    prompt = (f"STRATEGY:\n{BASE_STRATEGY}\n\nOBS: {summ}\n"
              f"ACTION_NAMES: {', '.join(f'{i}:{x}' for i,x in enumerate(names))}\n"
              f"Pick action. Reply ONLY JSON: {{\"action\":<int>,\"reason\":\"<short>\"}}")
    txt = chat(BASE_STRATEGY, prompt, max_tokens=120, temperature=0.3)
    act = parse_action(txt, n)
    if act == 58: act = 1
    o, r, t1, t2, inf = env.step(act)
    dt = round(time.time()-t0, 2)
    print(f"step{step} act={act} time={dt}s rew={r} kills={inf.get('kills')} hp={inf.get('hp')} mobs={len(summ['mobs'])}", flush=True)
    obs = o
    if t1 or t2:
        obs, info = env.reset(seed=42+step)
env.close()
