"""train_bc.py — collect dataset + train Behavioral Cloning on connectome features.

Pipeline:
1. Collect N steps of random play (state, action, next_state, reward)
2. Extract features using connectome_policy.obs_encoder
3. Train MLP policy (motor_decoder) via supervised learning on (features -> action)
4. Save trained policy
"""
import sys, os, json, time
sys.path.insert(0, 'D:/world-of-claudecraft')

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from python.connectome_policy import ConnectomePolicy
from python.gym_env import WoCFlyEnv


def collect_dataset(env, n_steps=500):
    """Collect random play dataset."""
    print(f'Collecting {n_steps} random samples...')
    
    obs_list, act_list, reward_list = [], [], []
    
    obs, _ = env.reset()
    
    for i in range(n_steps):
        action = env.action_space.sample()
        new_obs, reward, done, _, info = env.step(action)
        
        obs_list.append(obs)
        act_list.append(action)
        reward_list.append(reward)
        
        obs = new_obs
        
        if done:
            obs, _ = env.reset()
        
        if i % 100 == 0:
            print(f'  [{i}] r={reward:+.2f} tot={sum(reward_list):.1f}')
    
    return np.array(obs_list), np.array(act_list), np.array(reward_list)


class BCPolicy(nn.Module):
    """Simple BC policy: obs -> action logits."""
    
    def __init__(self, obs_dim, action_dim, hidden_dim=128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, action_dim)
        )
    
    def forward(self, obs):
        return self.net(obs)
    
    def get_action(self, obs):
        with torch.no_grad():
            logits = self.forward(obs)
            probs = torch.softmax(logits, dim=-1)
            action = torch.multinomial(probs, 1).squeeze(-1)
            log_prob = torch.log_softmax(logits, dim=-1).gather(1, action.unsqueeze(1)).squeeze(1)
            return action, log_prob


def train_bc(env, policy, optimizer, n_epochs=50, batch_size=64):
    """Train BC policy on collected dataset."""
    # Collect
    obs_data, act_data, reward_data = collect_dataset(env, n_steps=500)
    
    # Convert to tensors
    obs_t = torch.tensor(obs_data, dtype=torch.float32)
    act_t = torch.tensor(act_data, dtype=torch.long)
    
    dataset = TensorDataset(obs_t, act_t)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    
    # Train
    print(f'\nTraining BC for {n_epochs} epochs...')
    
    for epoch in range(n_epochs):
        total_loss = 0
        correct = 0
        total = 0
        
        for batch_obs, batch_act in loader:
            logits = policy(batch_obs)
            loss = nn.CrossEntropyLoss()(logits, batch_act)
            
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            
            total_loss += loss.item()
            pred = logits.argmax(dim=-1)
            correct += (pred == batch_act).sum().item()
            total += len(batch_act)
        
        if epoch % 10 == 0:
            print(f'  epoch {epoch}: loss={total_loss/len(loader):.4f} acc={correct/total:.2%}')
    
    return obs_data, act_data, reward_data


def main():
    env = WoCFlyEnv(max_steps=500)
    
    obs_dim = env.obs_dim
    action_dim = env.action_dim
    
    policy = BCPolicy(obs_dim, action_dim)
    optimizer = torch.optim.Adam(policy.parameters(), lr=1e-3)
    
    # Train
    obs_data, act_data, reward_data = train_bc(env, policy, optimizer, n_epochs=30)
    
    # Save
    torch.save({
        'state_dict': policy.state_dict(),
        'obs_dim': obs_dim,
        'action_dim': action_dim,
    }, 'data/bc_policy.pt')
    
    print('\nSaved to data/bc_policy.pt')
    
    # Test
    print('\nTesting BC policy...')
    obs, _ = env.reset()
    total_reward = 0
    
    for i in range(100):
        obs_t = torch.tensor(obs, dtype=torch.float32).unsqueeze(0)
        action, _ = policy.get_action(obs_t)
        action = action.item()
        
        obs, reward, done, _, info = env.step(action)
        total_reward += reward
        
        if i % 20 == 0:
            print(f'  [{i}] a={action} r={reward:+.2f} tot={total_reward:.1f} kills={info["kills"]}')
        
        if done:
            break
    
    print(f'\nTest reward: {total_reward:.1f}')


if __name__ == '__main__':
    main()
