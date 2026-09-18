"""train_ppo_offline.py — PPO on OfflineWoCEnv (fast, no network)."""
import sys, os
sys.path.insert(0, 'D:/world-of-claudecraft')

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.env_checker import check_env

from python.offline_woc_env import OfflineWoCEnv


def main():
    # Create fast env
    env = OfflineWoCEnv(max_steps=1000)
    
    # Check
    check_env(env)
    print('Env OK')
    
    # PPO
    print('Training PPO on offline env...')
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
    )
    
    # Train
    model.learn(total_timesteps=50000, progress_bar=False)
    
    # Save
    os.makedirs('data', exist_ok=True)
    model.save('data/ppo_fly_offline')
    print('Saved to data/ppo_fly_offline')
    
    # Eval
    print('\nEvaluating...')
    eval_reward = 0
    for ep in range(5):
        obs, _ = env.reset()
        episode_reward = 0
        done = False
        
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, done, _, info = env.step(action)
            episode_reward += reward
        
        eval_reward += episode_reward
        print(f'  Episode {ep}: {episode_reward:.1f}')
    
    print(f'Avg reward: {eval_reward/5:.1f}')


if __name__ == '__main__':
    main()
