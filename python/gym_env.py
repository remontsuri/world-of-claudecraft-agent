"""gym_env.py — Gymnasium env for WoC fly-brain agent.

Combines ConnectomePolicy rate-based network with WoC game observations.
Supports both live bridge and offline Gym simulation for BC/PPO training.
"""
import sys
sys.path.insert(0, 'D:/world-of-claudecraft')

import numpy as np
import torch
import gymnasium as gym
from gymnasium import spaces

from python.connectome_policy import ConnectomePolicy
from python.woc_game import WoCGameClient


class WoCFlyEnv(gym.Env):
    """Gymnasium env wrapping WoC game with connectome policy as brain."""
    
    metadata = {"render_modes": ["console"]}
    
    def __init__(self, obs_dim=16, action_dim=5, bridge_host='127.0.0.1', bridge_port=8791, max_steps=500):
        super().__init__()
        
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.max_steps = max_steps
        
        self.action_space = spaces.Discrete(action_dim)
        self.observation_space = spaces.Box(
            low=-10.0, high=10.0, shape=(obs_dim,), dtype=np.float32
        )
        
        # Connectome policy (rate-based)
        self.policy = ConnectomePolicy(obs_dim=obs_dim, action_dim=action_dim)
        self.policy.eval()
        
        # Game client
        self.game = WoCGameClient(bridge_host, bridge_port)
        
        # State
        self.n_steps = 0
        self.prev_info = None
        
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        # Reset connectome state
        self.policy.reset_state(batch_size=1)
        
        # Reset game
        self.game.respawn()
        info = self.game.snapshot()
        
        self.n_steps = 0
        self.prev_info = info
        
        obs = self._encode(info)
        return obs.numpy(), {}
    
    def _encode(self, info):
        """Encode WoC game info to observation vector."""
        if not info:
            return torch.zeros(self.obs_dim)
        
        player = info.get('player', {})
        player_pos = info.get('player_pos', [0, 0])
        nearby = info.get('nearby', [])
        
        mobs = [e for e in nearby if e.get('kind') == 'mob' and not e.get('dead', False)]
        hostile = [e for e in mobs if e.get('hostile')]
        nearest_mob = min(hostile if hostile else mobs, key=lambda e: e.get('dist', 999)) if mobs else None
        
        npcs = [e for e in nearby if e.get('kind') == 'npc']
        npcs_with_quests = [e for e in npcs if e.get('questIds') or e.get('questId')]
        nearest_npc = min(npcs_with_quests if npcs_with_quests else npcs, key=lambda e: e.get('dist', 999)) if npcs else None
        
        quests = info.get('quests', {})
        active_quests = quests.get('active', [])
        has_quest = len(active_quests) > 0
        
        hp_frac = player.get('hp', 100) / max(player.get('maxHp', 100), 1)
        
        features = [
            player_pos[0] / 1000,
            player_pos[1] / 1000,
            hp_frac,
            player.get('maxHp', 100) / 100,
            (nearest_mob.get('dist', 100) if nearest_mob else 100) / 100,
            hash(nearest_mob.get('type', '')) % 100 / 100 if nearest_mob else 0.5,
            (nearest_npc.get('dist', 100) if nearest_npc else 100) / 100,
            hash(nearest_npc.get('name', '')) % 100 / 100 if nearest_npc else 0.5,
            info.get('time', 12) / 24,
            (info.get('tick', 0) % 1000) / 1000,
            1.0 if has_quest else 0.0,
            hash(active_quests[0].get('id', '') if active_quests else '') % 10 / 10,
            min(len(info.get('inventory', [])), 64) / 64,
            min(info.get('copper', 0), 10000) / 10000,
            1.0 if player.get('inCombat', False) else 0.0,
            info.get('kills', 0) / 100,
        ]
        
        return torch.tensor(features[:self.obs_dim], dtype=torch.float32)
    
    def step(self, action):
        """Execute one action in the game."""
        # Safety: respawn if dead
        info = self.game.snapshot()
        if not info:
            obs = torch.zeros(self.obs_dim)
            return obs.numpy(), 0.0, True, False, {}
        
        player = info.get('player', {})
        if player.get('hp', 0) <= 0 or player.get('dead', False):
            self.game.respawn()
            info = self.game.snapshot()
        
        # Safety: flee if low HP OR too many hostile mobs
        hp_frac = player.get('hp', 100) / max(player.get('maxHp', 100), 1)
        nearby = info.get('nearby', [])
        hostile = [e for e in nearby if e.get('kind') == 'mob' and e.get('hostile', False)]
        n_hostile = len(hostile)
        close_hostile = [e for e in hostile if e.get('dist', 999) < 15]
        
        if hp_frac < 0.5 or n_hostile >= 3 or len(close_hostile) >= 2:
            # Flee from ALL hostile mobs
            if hostile:
                ex = info['player_pos'][0] - np.mean([m['x'] for m in hostile[:5]])
                ez = info['player_pos'][1] - np.mean([m['z'] for m in hostile[:5]])
                emag = max(np.hypot(ex, ez), 0.1)
                # Flee further if very low hp
                dist = 25 if hp_frac < 0.3 else 15
                tx = info['player_pos'][0] + (ex/emag) * dist
                tz = info['player_pos'][1] + (ez/emag) * dist
                self.game.navigate(tx, tz, max_steps=8)
                obs = self._encode(self.game.snapshot())
                return obs.numpy(), -0.05, False, False, {'flee': True}
        
        # Execute action with pre-navigation
        new_info = self._execute(action, info)
        
        # Reward
        reward = self._reward(info, new_info)
        
        self.n_steps += 1
        
        # Encode
        obs = self._encode(new_info)
        
        # Check done
        done = self.n_steps >= self.max_steps
        
        # Info
        extra = {
            'kills': new_info.get('kills', 0),
            'copper': new_info.get('copper', 0),
            'quests_done': new_info.get('quests_done', 0),
            'deaths': new_info.get('deaths', 0),
        }
        
        self.prev_info = new_info
        
        return obs.numpy(), float(reward), done, False, extra
    
    def _execute(self, action, info):
        """Execute action with pre-navigation."""
        nearby = info.get('nearby', [])
        
        if action == 0:  # farm
            mobs = [e for e in nearby if e.get('kind') == 'mob' and e.get('hostile', False) and not e.get('dead', False)]
            if mobs:
                nearest = min(mobs, key=lambda e: e.get('dist', 999))
                if nearest.get('dist', 999) > 10:
                    self.game.navigate(nearest['x'], nearest['z'], max_steps=15)
            return self.game.step(0)
        
        elif action == 1:  # loot
            lootables = [e for e in nearby if e.get('lootable', False) and not e.get('looted', False)]
            if lootables:
                nearest = min(lootables, key=lambda e: e.get('dist', 999))
                if nearest.get('dist', 999) > 8:
                    self.game.navigate(nearest['x'], nearest['z'], max_steps=10)
            return self.game.step(1)
        
        elif action == 2:  # accept quest
            npcs = [e for e in nearby if e.get('kind') == 'npc' and (e.get('questIds') or e.get('questId'))]
            if npcs:
                nearest = min(npcs, key=lambda e: e.get('dist', 999))
                if nearest.get('dist', 999) > 8:
                    self.game.navigate(nearest['x'], nearest['z'], max_steps=15)
            return self.game.step(2)
        
        elif action == 3:  # turn in
            return self.game.step(3)
        
        elif action == 4:  # sell
            return self.game.step(4)
        
        else:
            return info
    
    def _reward(self, prev_info, info):
        if not prev_info or not info:
            return 0.0
        
        reward = 0.0
        
        # Kills
        d_kills = info.get('kills', 0) - prev_info.get('kills', 0)
        if d_kills > 0:
            reward += 10.0 * d_kills
        
        # Quests
        d_quests = info.get('quests_done', 0) - prev_info.get('quests_done', 0)
        if d_quests > 0:
            reward += 20.0 * d_quests
        
        # Copper
        d_copper = info.get('copper', 0) - prev_info.get('copper', 0)
        if d_copper > 0:
            reward += 0.01 * d_copper
        
        # Deaths
        d_deaths = info.get('deaths', 0) - prev_info.get('deaths', 0)
        if d_deaths > 0:
            reward -= 15.0 * d_deaths
        
        # XP
        d_xp = info.get('xp', 0) - prev_info.get('xp', 0)
        if d_xp > 0:
            reward += 0.1 * d_xp
        
        # HP penalty (survival)
        hp_frac = info.get('player', {}).get('hp', 100) / max(info.get('player', {}).get('maxHp', 100), 1)
        if hp_frac < 0.5:
            reward -= 0.1 * (0.5 - hp_frac)
        
        return reward


if __name__ == '__main__':
    env = WoCFlyEnv(max_steps=100)
    obs, _ = env.reset()
    
    total_reward = 0
    for i in range(100):
        action = env.action_space.sample()
        obs, reward, done, _, info = env.step(action)
        total_reward += reward
        if i % 20 == 0:
            print(f'step {i}: a={action} r={reward:+.2f} tot={total_reward:.1f} kills={info["kills"]}')
        if done:
            break
    
    print(f'\nDone. Total reward: {total_reward:.1f}')
