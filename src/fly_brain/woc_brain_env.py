"""woc_brain_env.py — Gymnasium env integrating LIF brain with WoC game.

Full pipeline:
  WoC observation → SensorAdapter (photoreceptors) → BrainEngine (LIF 138K) → MotorDecoder (WTA) → WoC action
"""
import numpy as np
import torch
import gymnasium as gym
from gymnasium import spaces
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fly_brain.engine import BrainEngine
from src.fly_brain.sensor_adapter import SensorAdapter
from src.fly_brain.motor_decoder import MotorDecoder
from src.fly_brain.da_stdp import DopamineModulatedSTDP


class WoCFlyBrainEnv(gym.Env):
    """WoC env with full LIF brain control."""
    
    metadata = {"render_modes": ["console"]}
    
    def __init__(self, action_dim=7, max_steps=500, bridge_host='127.0.0.1', 
                 bridge_port=8791, device='cpu', use_brain=True):
        super().__init__()
        
        self.action_dim = action_dim
        self.max_steps = max_steps
        self.use_brain = use_brain
        
        self.action_space = spaces.Discrete(action_dim)
        self.observation_space = spaces.Box(
            low=-10.0, high=10.0, shape=(16,), dtype=np.float32
        )
        
        # Brain components
        self.device = device
        self.brain = None
        self.sensor = None
        self.motor = None
        self.stdp = None
        
        # Game client
        from python.woc_game import WoCGameClient
        self.game = WoCGameClient(bridge_host, bridge_port)
        
        # State
        self.n_steps = 0
        self.prev_info = None
    
    def _init_brain(self):
        """Initialize brain components."""
        if self.brain is None:
            self.brain = BrainEngine(device=self.device, batch=1)
            self.brain.initialize()
            
            self.sensor = SensorAdapter()
            self.motor = MotorDecoder(self.brain.n_neurons)
            self.stdp = DopamineModulatedSTDP(device=self.device)
            
            print(f"[env] Brain initialized: {self.brain.n_neurons} neurons")
    
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        if self.use_brain:
            self._init_brain()
        
        # Reset game
        self.game.respawn()
        info = self.game.snapshot()
        
        self.n_steps = 0
        self.prev_info = info
        
        obs = self._encode_obs(info)
        return obs, {}
    
    def _encode_obs(self, info):
        """Encode WoC info to 16-dim observation (compatible with play_fly_live)."""
        if not info:
            return np.zeros(16, dtype=np.float32)
        
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
        
        obs = np.array([
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
        ], dtype=np.float32)
        
        return obs
    
    def step(self, action=None):
        """Execute one step with brain control."""
        # Safety: respawn if dead
        info = self.game.snapshot()
        if not info:
            return np.zeros(16, dtype=np.float32), 0.0, True, False, {}
        
        player = info.get('player', {})
        if player.get('hp', 0) <= 0 or player.get('dead', False):
            self.game.respawn()
            info = self.game.snapshot()
        
        obs = self._encode_obs(info)
        
        # Brain control
        if self.use_brain and self.brain is not None and action is None:
            # Encode observation → photoreceptor rates
            rates = self.sensor.encode(obs, max_rate=100.0)
            
            # Set rates in brain
            rates_tensor = torch.tensor(rates, dtype=torch.float32, device=self.device)
            rates_tensor = rates_tensor.unsqueeze(0)  # add batch dim
            
            # Map photoreceptor rates to brain input indices
            # (use first N indices for photoreceptors)
            n_phot = len(rates)
            brain_rates = torch.zeros(1, self.brain.n_neurons, device=self.device)
            brain_rates[0, :min(n_phot, self.brain.n_neurons)] = rates_tensor[0, :min(n_phot, self.brain.n_neurons)]
            
            # Step brain
            spikes = self.brain.step(brain_rates, n_steps=10)
            
            # Decode action via WTA
            action = self.motor.decode(spikes[0])
        
        # Execute action
        new_info = self._execute(action, info)
        
        # Reward
        reward = self._reward(info, new_info)
        
        # DA-STDP update
        if self.use_brain and self.stdp is not None:
            # Map game events to dopamine
            prev_hp = self.prev_info.get('player', {}).get('hp', 100) if self.prev_info else 100
            curr_hp = new_info.get('player', {}).get('hp', 100)
            
            if curr_hp < prev_hp:
                self.stdp.process_event('damage')
            elif new_info.get('kills', 0) > (self.prev_info.get('kills', 0) if self.prev_info else 0):
                self.stdp.process_event('kill')
        
        self.n_steps += 1
        done = self.n_steps >= self.max_steps
        
        obs = self._encode_obs(new_info)
        
        extra = {
            'kills': new_info.get('kills', 0),
            'copper': new_info.get('copper', 0),
            'quests_done': new_info.get('quests_done', 0),
            'deaths': new_info.get('deaths', 0),
        }
        
        self.prev_info = new_info
        
        return obs, float(reward), done, False, extra
    
    def _execute(self, action, info):
        """Execute action in game."""
        nearby = info.get('nearby', [])
        
        if action == 0:  # move forward (explore)
            return self.game.step(0)
        elif action == 1:  # turn left
            self.game.raw_move('turnLeft')
            return self.game.snapshot()
        elif action == 2:  # turn right
            self.game.raw_move('turnRight')
            return self.game.snapshot()
        elif action == 3:  # attack/farm
            mobs = [e for e in nearby if e.get('kind') == 'mob' and e.get('hostile', False) and not e.get('dead', False)]
            if mobs:
                nearest = min(mobs, key=lambda e: e.get('dist', 999))
                if nearest.get('dist', 999) < 7:
                    return self.game.step(0)
            return self.game.step(0)
        elif action == 4:  # target nearest
            return self.game.step(0)
        elif action == 5:  # loot/quest
            return self.game.step(1)
        elif action == 6:  # rest
            return info
        else:
            return info
    
    def _reward(self, prev_info, info):
        """Compute reward."""
        if not prev_info or not info:
            return 0.0
        
        reward = 0.0
        
        d_kills = info.get('kills', 0) - prev_info.get('kills', 0)
        if d_kills > 0:
            reward += 10.0 * d_kills
        
        d_quests = info.get('quests_done', 0) - prev_info.get('quests_done', 0)
        if d_quests > 0:
            reward += 20.0 * d_quests
        
        d_deaths = info.get('deaths', 0) - prev_info.get('deaths', 0)
        if d_deaths > 0:
            reward -= 15.0 * d_deaths
        
        hp_frac = info.get('player', {}).get('hp', 100) / max(info.get('player', {}).get('maxHp', 100), 1)
        if hp_frac < 0.3:
            reward -= 0.2
        
        return reward


if __name__ == '__main__':
    print("Testing WoCFlyBrainEnv...")
    
    env = WoCFlyBrainEnv(max_steps=50, use_brain=False)  # test without brain first
    
    obs, _ = env.reset()
    total_reward = 0
    
    for i in range(50):
        action = env.action_space.sample()
        obs, reward, done, _, info = env.step(action)
        total_reward += reward
        if i % 10 == 0:
            print(f"  Step {i}: a={action} r={reward:+.2f} tot={total_reward:.1f}")
        if done:
            break
    
    print(f"\nTest complete. Total reward: {total_reward:.1f}")
