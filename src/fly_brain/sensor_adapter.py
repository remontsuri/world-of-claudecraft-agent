"""sensor_adapter.py — map WoC game observations to fly photoreceptor inputs."""
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class PhotoreceptorMapper:
    def __init__(self, n_brightness=400, n_color=100, seed=42):
        self.n_brightness = n_brightness
        self.n_color = n_color
        self.n_total = n_brightness + n_color
        
        rng = np.random.RandomState(seed)
        self.r1r6_angle = rng.uniform(-np.pi, np.pi, n_brightness)
        self.r1r6_baseline = 5.0
        self.r8_baseline = 3.0
    
    def encode(self, obs, max_rate=200.0):
        obs = np.asarray(obs, dtype=np.float32).reshape(-1)
        
        mob_dist = obs[4] * 100.0
        npc_dist = obs[6] * 100.0
        hp_frac = obs[2]
        in_combat = obs[14]
        time_of_day = obs[8]
        
        mob_proximity = np.exp(-mob_dist / 30.0)
        npc_proximity = np.exp(-npc_dist / 25.0)
        
        r1r6_rates = self.r1r6_baseline * np.ones(self.n_brightness)
        r1r6_rates += mob_proximity * max_rate * 0.5
        r1r6_rates += npc_proximity * max_rate * 0.3
        r1r6_rates += in_combat * max_rate * 0.2
        
        day_factor = 0.5 + 0.5 * np.sin(time_of_day * 2 * np.pi - np.pi/2)
        r1r6_rates *= (0.3 + 0.7 * day_factor)
        
        if hp_frac < 0.3:
            r1r6_rates *= (1.0 + (0.3 - hp_frac) * 2.0)
        
        r8_rates = self.r8_baseline * np.ones(self.n_color)
        has_quest = obs[10]
        r8_rates += has_quest * max_rate * 0.2
        
        rates = np.concatenate([r1r6_rates, r8_rates]).astype(np.float32)
        rates = np.clip(rates, 0, max_rate)
        return rates


class SensorAdapter:
    def __init__(self, n_brightness=400, n_color=100):
        self.mapper = PhotoreceptorMapper(n_brightness, n_color)
        self.n_total = n_brightness + n_color
    
    def encode(self, obs, max_rate=200.0):
        return self.mapper.encode(obs, max_rate)
