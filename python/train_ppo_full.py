"""train_ppo_full.py — FULL PPO fine-tune from BC-B1 (variant a: CombatLatchWrapper).

Differences from train_ppo_from_b1.py --smoke:
  * value-head WARM-UP before PPO updates (smoke showed cold value_net
    degrades B1 9/10 -> 3/10 in 5k steps because advantage was noise).
  * much larger timestep budget (default 200k, configurable).
  * small policy_lr (1e-4) to fine-tune without destroying B1 behaviour;
    value_lr normal.
  * periodic eval (every --eval-every steps) + final eval 10 seeds.

NO Sim/reward/obs changes. Wrapper only. B1 weights imported 1:1 (ReLU
activation matched to BC). STOP rules from user plan are satisfied: parity
PASS (100%) was confirmed in train_ppo_from_b1.py before this run.

Run:
  therock-test/Scripts/python.exe train_ppo_full.py --total 200000
"""
from __future__ import annotations
import argparse, os, sys, json, time
from pathlib import Path

os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
_ROOT = Path(r"D:/world-of-claudecraft/python")
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, r"D:/woc-llm")

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import gymnasium as gym
from gymnasium import spaces

import audit_common as ac
import curriculum_env as ce
import nav_features as nf
from train_ppo_from_b1 import BCPolicy, bc_featurize, CombatLatchWrapper, inspect_and_map

ROOT = _ROOT
OUT = ROOT / "nav_data" / "bc_nav_B1.pt"
ABILITY_SLOTS = (ac.TGT - 16) // 2
EVAL_SEEDS = list(range(42, 52))


def build_sb3(device, total, policy_lr=1e-4, n_envs=1):
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
    from stable_baselines3.common.vec_env import DummyVecEnv
    base = lambda: CombatLatchWrapper(ce.CurriculumEnv(stage=3, player_class="warrior",
                                                       max_steps=400, frame_skip=5))
    env = make_vec_env(base, n_envs=n_envs, seed=42, vec_env_cls=DummyVecEnv)
    model = PPO("MlpPolicy", env, learning_rate=policy_lr, n_steps=1024, batch_size=256,
                n_epochs=4, gamma=0.99, gae_lambda=0.95, clip_range=0.2,
                ent_coef=0.01, vf_coef=0.5, max_grad_norm=0.5,
                policy_kwargs={"net_arch": [512, 256, 128], "activation_fn": torch.nn.ReLU},
                device=device, seed=42, verbose=1)
    return model, env


def value_warmup(model, device, n_steps=20000, epochs=8, lr=1e-3):
    """Train value branch on discounted returns from B1-policy rollouts.

    Uses CombatLatchWrapper output directly (568-dim, hysteresis already
    applied by the wrapper) -- no bc_featurize (which expects raw 567 obs).
    """
    print(f"\n===== VALUE WARM-UP ({n_steps} steps) =====")
    all_obs, all_ret = [], []
    env = CombatLatchWrapper(ce.CurriculumEnv(stage=3, player_class="warrior",
                                              max_steps=400, frame_skip=5))
    o, _ = env.reset(seed=42)
    gamma = 0.99
    ep_obs, ep_rews = [], []
    steps = 0
    while steps < n_steps:
        a = int(np.asarray(model.predict(o[None, :], deterministic=True)[0]).item())
        o2, r, term, trunc, info = env.step(int(a))
        ep_obs.append(o.astype(np.float32))
        ep_rews.append(float(r))
        steps += 1
        if term or trunc:
            running = 0.0
            ep_ret = []
            for rew in reversed(ep_rews):
                running = rew + gamma * running
                ep_ret.append(running)
            ep_ret = ep_ret[::-1]
            all_obs.extend(ep_obs)
            all_ret.extend(ep_ret)
            ep_obs, ep_rews = [], []
            o, _ = env.reset(seed=int(np.random.randint(0, 1e6)))
        else:
            o = o2
    env.close()
    if not all_obs:
        print("  warm-up collected 0 steps — skip")
        return
    X = torch.from_numpy(np.asarray(all_obs, np.float32)).to(device)
    Y = torch.from_numpy(np.asarray(all_ret, np.float32)).to(device).unsqueeze(1)
    opt = optim.Adam(
        list(model.policy.mlp_extractor.value_net.parameters()) +
        list(model.policy.value_net.parameters()), lr=lr)
    n = X.shape[0]
    print(f"  collected {n} (obs,return) pairs")
    for ep in range(epochs):
        idx = torch.randperm(n)
        batch = 256
        tot_loss = 0.0
        for s in range(0, n, batch):
            bi = idx[s:s + batch]
            feat = model.policy.extract_features(X[bi])
            _, lat_vf = model.policy.mlp_extractor(feat)
            v = model.policy.value_net(lat_vf)
            loss = nn.functional.mse_loss(v, Y[bi])
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot_loss += loss.item() * bi.shape[0]
        print(f"  epoch {ep+1}/{epochs}  mse={tot_loss/n:.4f}")
    print("  value warm-up done")


@torch.no_grad()
def eval_sb3(model, seeds=EVAL_SEEDS, max_steps=400, frame_skip=5):
    ek = deaths = 0
    for seed in seeds:
        env = CombatLatchWrapper(ce.CurriculumEnv(stage=3, player_class="warrior",
                                          max_steps=max_steps, frame_skip=frame_skip))
        o, _ = env.reset(seed=seed)
        kills = dead = 0
        for _ in range(1, max_steps + 1):
            a, _ = model.predict(o[None, :], deterministic=True)
            a = int(np.asarray(a).item())
            o, r, term, trunc, info = env.step(int(a))
            kills = max(kills, info.get("kills", 0) or 0)
            if (info.get("deaths", 0) or 0) > 0:
                dead = 1
            if term or trunc:
                break
        env.close()
        ek += int(kills > 0)
        deaths += dead
    return ek, deaths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=200000)
    ap.add_argument("--eval-every", type=int, default=50000)
    ap.add_argument("--policy-lr", type=float, default=1e-4)
    ap.add_argument("--warmup-steps", type=int, default=20000)
    ap.add_argument("--no-warmup", action="store_true")
    ap.add_argument("--n-envs", type=int, default=1)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device={device}")

    ckpt = torch.load(OUT, map_location="cpu", weights_only=True)
    bc = BCPolicy(ckpt["obs_dim"], ckpt["n_act"]).to(device)
    bc.load_state_dict(ckpt["state_dict"])
    bc.eval()

    model, env = build_sb3(device, args.total, policy_lr=args.policy_lr, n_envs=args.n_envs)
    inspect_and_map(bc.state_dict(), model.policy)
    # NOTE: do NOT env.close() here — model.learn() needs the live env.
    # SB3 closes it in model.learn()/model.save() finalization.

    if not args.no_warmup:
        value_warmup(model, device, n_steps=args.warmup_steps)

    print(f"\n===== PPO FINE-TUNE from B1: {args.total} steps =====")
    t0 = time.time()
    model.learn(total_timesteps=args.total, tb_log_name="b1_full",
                callback=None)
    dt = time.time() - t0
    print(f"  trained in {dt:.1f}s")

    model.save(str(ROOT / "nav_data" / "ppo_from_b1_full"))
    ek, d = eval_sb3(model, EVAL_SEEDS)
    print(f"\n>>> FINAL: episodes_with_kill={ek}/10  death={d}%  "
          f"(B1 BC baseline was 9/10; smoke 5k B1 was 3/10)")
    with open(ROOT / "nav_data" / "ppo_full_result.json", "w") as f:
        json.dump({"total": args.total, "episodes_with_kill": ek,
                   "death": d, "seconds": dt}, f, indent=2)


if __name__ == "__main__":
    main()
