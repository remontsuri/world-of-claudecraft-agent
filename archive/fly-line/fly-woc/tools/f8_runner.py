#!/usr/bin/env python3
"""F8 runner: прогнать все условия на 3 сидах и сохранить benchmark_v3.json."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("WOC_PYTHON_PATH", "D:/woc-game/python")
import numpy as np, torch
from progress_eval import build, run_episode, WoWClassicEnv, ACCEPTANCE
from device_utils import resolve_device
from obs_layout import configure as _configure_layout
from quest_oracle import load_table, oracle_vector
from pathlib import Path

CONDITIONS = [
    # (policy, circuit, label)
    ("fly-sampled", None, "our"),
    ("fly", None, "fly-argmax"),
    ("fly-sampled", "data/circuit_rewired.json", "rewired"),
    ("fly-sampled", "data/circuit_er.json", "er"),
    ("fly-sampled-silenced", None, "silenced"),
    ("fly-sampled-untrained", None, "untrained"),
    ("mlp-sampled", None, "mlp"),
]
SEEDS = [900001, 900101, 900201]
EPISODES = 5
MAX_STEPS = 1200
OUT = Path(__file__).parent.parent / "fly-woc" / "outputs" / "benchmark_v3.json"
DEVICE = resolve_device(None)

def main():
    results = {}
    print(f"[f8] device={DEVICE}", flush=True)
    for seed0 in SEEDS:
        for policy, circuit, label in CONDITIONS:
            env = WoWClassicEnv(player_class="warrior", max_steps=8000)
            _configure_layout(obs_size=env.observation_space.shape[0], n_actions=env.action_space.n)
            ckpt = Path(__file__).parent.parent / "fly-woc" / "outputs" / "params_fly_v2.pt"
            ckpt = ckpt if ckpt.exists() else None
            base = policy[:-len("-sampled")] if policy.endswith("-sampled") else policy
            brain, net = build(policy, ckpt, 20260914, env.observation_space.shape[0],
                               env.action_space.n, oracle_extra=0, circuit=circuit, device=DEVICE)
            rows = []
            for k in range(EPISODES):
                r = run_episode(env, brain, net, policy, seed0 + k, MAX_STEPS)
                rows.append(r)
                print(f"  seed={seed0+k} {label:18s} rew={r['reward']:8.3f} q={r['quests_done']} k={r['kills']} d={r['deaths']}")
            agg = {key: float(np.mean([r[key] for r in rows]))
                   for key in ("level", "xp", "kills", "deaths", "quests_done", "travel_norm", "reward")}
            key = f"{label}_s{seed0}"
            results[key] = {"label": label, "seed0": seed0, "aggregate": agg, "episodes": rows}
            env.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"conditions": results, "meta": {"seeds": SEEDS, "episodes": EPISODES, "max_steps": MAX_STEPS}}, indent=1))
    print(f"\nwrote {OUT}")

    # Сводная таблица
    print("\n=== Сводка (среднее по трём сидам) ===")
    print(f"{'condition':18s} {'reward':>8s} {'quests':>7s} {'kills':>6s} {'deaths':>7s}")
    labels = ["our", "rewired", "er", "silenced", "untrained", "mlp", "fly-argmax"]
    for label in labels:
        rews, qs, ks, ds = [], [], [], []
        for seed0 in SEEDS:
            key = f"{label}_s{seed0}"
            if key in results:
                a = results[key]["aggregate"]
                rews.append(a["reward"]); qs.append(a["quests_done"])
                ks.append(a["kills"]); ds.append(a["deaths"])
        if rews:
            print(f"{label:18s} {np.mean(rews):8.3f} {np.mean(qs):7.1f} {np.mean(ks):6.1f} {np.mean(ds):7.1f}")

if __name__ == "__main__":
    main()
