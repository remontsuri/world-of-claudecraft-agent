"""PPO fine-tuning on top of the hierarchical adapter (Step 6 of the plan).

High-level policy (MaskablePPO) learns to SELECT skills (farm / loot / heal / ...);
the low-level layer (B1 / obs.ts ACTIONS) executes them inside HierarchicalWoWEnv.
Action masking (env.action_masks()) keeps PPO off unsupported/dead branches
(craft/equip/buy have no server cmd; sell_junk/gather/quest need absent world
preconditions) — this is the fix for the "node server crash during 20k run" gap
in TRAINING.md: an unmasked agent explores empty skill branches -> nav into the
void -> server crash.

Run:  env -u PYTHONPATH /d/woc-llm/therock-test/Scripts/python.exe train_hierarchical.py \
          --steps 20000 --out models/hl_ppo --max_steps 500
Smoke: env -u PYTHONPATH /d/woc-llm/therock-test/Scripts/python.exe train_hierarchical.py --smoke
"""
import argparse
import os
import numpy as np
import gymnasium as gym
from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.callbacks import MaskableEvalCallback
from sb3_contrib.common.maskable.utils import get_action_masks

from hierarchical_env import HierarchicalWoWEnv, make_hl_env, N_SKILLS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=20000)
    ap.add_argument("--out", type=str, default="models/hl_ppo")
    ap.add_argument("--player_class", type=str, default="warrior")
    ap.add_argument("--max_steps", type=int, default=2000)
    ap.add_argument("--n_envs", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--eval", action="store_true", help="run eval callback")
    ap.add_argument("--smoke", action="store_true", help="1-step learn + predict, no long run")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    env = make_hl_env(
        player_class=args.player_class,
        max_steps=args.max_steps,
        seed=args.seed,
    )

    model = MaskablePPO(
        "MlpPolicy",
        env,
        verbose=1,
        learning_rate=3e-4,
        n_steps=256,
        batch_size=64,
        n_epochs=4,
        gamma=0.95,
        device="cuda",  # TheRock ROCm GPU (torch sees it as cuda)
        tensorboard_log=os.path.join(args.out, "tb"),
    )

    if args.smoke:
        # Prove the masked pipeline initializes + steps without crashing.
        # One learn step + one masked predict. No long GPU burn.
        model.learn(total_timesteps=1)
        obs, _ = env.reset(seed=args.seed)
        action, _ = model.predict(obs, action_masks=get_action_masks(env), deterministic=True)
        assert 0 <= int(action) < N_SKILLS
        obs, r, term, trunc, _ = env.step(int(action))
        print(f"SMOKE OK: 1 learn step + masked predict action={int(action)} reward={float(r):.3f}")
        env.close()
        return

    if args.eval:
        eval_env = make_hl_env(player_class=args.player_class, max_steps=args.max_steps, seed=args.seed + 999)
        eval_cb = MaskableEvalCallback(
            eval_env,
            best_model_save_path=args.out,
            log_path=os.path.join(args.out, "eval"),
            eval_freq=2000,
            deterministic=True,
            render=False,
        )
        model.learn(total_timesteps=args.steps, callback=eval_cb)
    else:
        model.learn(total_timesteps=args.steps)

    model.save(os.path.join(args.out, "final"))
    print(f"Saved: {os.path.join(args.out, 'final')}.zip")

    # quick eval: mean reward over a few episodes with the trained policy
    eval_env = make_hl_env(player_class=args.player_class, max_steps=args.max_steps, seed=args.seed + 999)
    mean_r = 0.0
    n_eps = 5
    for _ in range(n_eps):
        obs, _ = eval_env.reset()
        done = False
        ep_r = 0.0
        while not done:
            action, _ = model.predict(obs, action_masks=get_action_masks(eval_env), deterministic=True)
            obs, r, term, trunc, _ = eval_env.step(int(action))
            ep_r += float(r)
            done = bool(term) or bool(trunc)
        mean_r += ep_r
    print(f"Trained mean episode reward ({n_eps} eps): {mean_r / n_eps:.2f}")
    env.close()


if __name__ == "__main__":
    main()
