"""train_ppo.py — PPO training on WoCFlyEnv with stable-baselines3.

Usage:
    python train_ppo.py --steps 10000 --eval-every 2000
"""
import sys, os, time, argparse
sys.path.insert(0, 'D:/world-of-claudecraft')

import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.env_checker import check_env

from python.gym_env import WoCFlyEnv


def make_env(max_steps=500):
    """Create WoCFlyEnv instance."""
    def _init():
        return WoCFlyEnv(max_steps=max_steps)
    return _init


def main():
    parser = argparse.ArgumentParser(description='PPO training for WoC fly agent')
    parser.add_argument('--steps', type=int, default=10000, help='total training steps')
    parser.add_argument('--eval-every', type=int, default=2000, help='eval frequency')
    parser.add_argument('--max-steps', type=int, default=500, help='max steps per episode')
    parser.add_argument('--save-path', default='data/ppo_fly', help='model save path')
    args = parser.parse_args()
    
    # Create env
    env = WoCFlyEnv(max_steps=args.max_steps)
    
    # Check env
    print('Checking env...')
    check_env(env)
    print('Env OK')
    
    # PPO
    print(f'\nTraining PPO for {args.steps} steps...')
    
    model = PPO(
        'MlpPolicy',
        env,
        learning_rate=3e-4,
        n_steps=256,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        verbose=1,
        device='cpu',
        #
    )
    
    # Train with periodic eval
    total_steps = 0
    best_reward = -float('inf')
    
    while total_steps < args.steps:
        # Train
        model.learn(total_timesteps=args.eval_every, reset_num_timesteps=False)
        total_steps += args.eval_every
        
        # Eval
        print(f'\n=== Eval at step {total_steps} ===')
        eval_reward = evaluate(model, env, n_episodes=3)
        print(f'Eval reward: {eval_reward:.1f}')
        
        if eval_reward > best_reward:
            best_reward = eval_reward
            model.save(f'{args.save_path}_best')
            print(f'New best! Saved to {args.save_path}_best')
    
    # Final save
    model.save(args.save_path)
    print(f'\nTraining done. Final model saved to {args.save_path}')
    
    # Final eval
    final_reward = evaluate(model, env, n_episodes=5)
    print(f'Final eval reward: {final_reward:.1f}')


def evaluate(model, env, n_episodes=3):
    """Evaluate model over n_episodes."""
    total_rewards = []
    
    for ep in range(n_episodes):
        obs, _ = env.reset()
        episode_reward = 0
        done = False
        
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, done, _, info = env.step(action)
            episode_reward += reward
        
        total_rewards.append(episode_reward)
        print(f'  Episode {ep}: reward={episode_reward:.1f}')
    
    return np.mean(total_rewards)


if __name__ == '__main__':
    main()
