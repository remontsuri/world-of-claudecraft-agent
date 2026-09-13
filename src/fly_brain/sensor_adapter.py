"""sensor_adapter.py — map WoC game observations to fly photoreceptor inputs.

Maps the 16-dim WoC observation vector to 3,335 R1-R6 (brightness) + 811 R8 (color)
photoreceptor neurons using vector-coded receptive fields.
"""
import numpy as np
import torch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class PhotoreceptorMapper:
    """Maps WoC observations to photoreceptor firing rates.
    
    R1-R6 (3,335 neurons): brightness/intensity, monochrome
    R8 (811 neurons): color channels (simplified to RGB-like)
    """
    
    def __init__(self, n_brightness=3335, n_color=811, seed=42):
        self.n_brightness = n_brightness
        self.n_color = n_color
        self.n_total = n_brightness + n_color
        
        # Create fixed random receptive fields for each photoreceptor
        # Each neuron has a preferred direction (angle) and distance sensitivity
        rng = np.random.RandomState(seed)
        
        # R1-R6: brightness neurons arranged in a rough visual field
        # Preferred angle: -pi to pi (full visual field)
        self.r1r6_angle = rng.uniform(-np.pi, np.pi, n_brightness)
        # Preferred distance: 0 (close) to 1 (far)
        self.r1r6_dist_pref = rng.beta(2, 5, n_brightness)  # most prefer close
        # Spatial tuning width
        self.r1r6_width = rng.uniform(0.3, 1.2, n_brightness)
        
        # R8: color neurons (RGB-like channels)
        # Assign to 3 color channels
        self.r8_channel = rng.choice([0, 1, 2], n_color)  # R, G, B
        self.r8_angle = rng.uniform(-np.pi, np.pi, n_color)
        self.r8_dist_pref = rng.beta(2, 5, n_color)
        self.r8_width = rng.uniform(0.3, 1.2, n_color)
        
        # Baseline firing rates (Hz)
        self.r1r6_baseline = 5.0
        self.r8_baseline = 3.0
    
    def encode(self, obs, max_rate=100.0):
        """Encode 16-dim WoC observation to photoreceptor rates.
        
        obs: array-like of shape (16,) with:
            [0] pos_x / 1000
            [1] pos_z / 1000
            [2] hp_frac (0-1)
            [3] maxHp / 100
            [4] nearest_mob_dist / 100
            [5] nearest_mob_type_hash (0-1)
            [6] nearest_npc_dist / 100
            [7] nearest_npc_name_hash (0-1)
            [8] time / 24
            [9] tick / 1000
            [10] has_quest (0/1)
            [11] active_quest_id_hash (0-1)
            [12] inventory_count / 64
            [13] copper / 10000
            [14] in_combat (0/1)
            [15] kills / 100
        
        Returns: rates tensor of shape (n_total,) in Hz
        """
        obs = np.asarray(obs, dtype=np.float32).reshape(-1)
        
        # Extract relevant features
        mob_dist = obs[4] * 100.0  # denormalize
        mob_type = obs[5]
        npc_dist = obs[6] * 100.0
        npc_type = obs[7]
        hp_frac = obs[2]
        in_combat = obs[14]
        time_of_day = obs[8]
        
        # === R1-R6: Brightness neurons ===
        # Brightness increases when:
        # - Mob is close (strong response)
        # - NPC is close (moderate response)
        # - In combat (arousal)
        # - Daytime (more light)
        
        # Distance tuning: closer = brighter
        mob_proximity = np.exp(-mob_dist / 30.0)  # 1.0 at dist=0, ~0.3 at dist=30
        npc_proximity = np.exp(-npc_dist / 25.0)
        
        # Angle tuning: mobs/NPCs in front of player get stronger response
        # (simplified: assume player faces -Z, so objects at relative angle)
        mob_angle_factor = np.cos(self.r1r6_angle) * 0.5 + 0.5  # 0-1
        npc_angle_factor = np.cos(self.r1r6_angle) * 0.3 + 0.5
        
        # Combine: baseline + mob response + npc response + arousal
        r1r6_rates = self.r1r6_baseline * np.ones(self.n_brightness)
        r1r6_rates += mob_proximity * max_rate * 0.5 * mob_angle_factor
        r1r6_rates += npc_proximity * max_rate * 0.3 * npc_angle_factor
        r1r6_rates += in_combat * max_rate * 0.2  # arousal boost
        
        # Day/night modulation (time 0-1, assume 0.5=noight)
        day_factor = 0.5 + 0.5 * np.sin(time_of_day * 2 * np.pi - np.pi/2)
        r1r6_rates *= (0.3 + 0.7 * day_factor)
        
        # HP modulation: low HP = red alert (increase brightness)
        if hp_frac < 0.3:
            r1r6_rates *= (1.0 + (0.3 - hp_frac) * 2.0)
        
        # === R8: Color neurons ===
        # Color response: mobs = red channel, NPCs = green channel, quest = blue
        r8_rates = self.r8_baseline * np.ones(self.n_color)
        
        # Mob → red channel (channel 0)
        mob_color_mask = (self.r8_channel == 0)
        r8_rates[mob_color_mask] += mob_proximity * max_rate * 0.4 * mob_color_mask[mob_color_mask]
        
        # NPC → green channel (channel 1)
        npc_color_mask = (self.r8_channel == 1)
        r8_rates[npc_color_mask] += npc_proximity * max_rate * 0.4 * npc_color_mask[npc_color_mask]
        
        # Quest → blue channel (channel 2)
        has_quest = obs[10]
        quest_color_mask = (self.r8_channel == 2)
        r8_rates[quest_color_mask] += has_quest * max_rate * 0.3 * quest_color_mask[quest_color_mask]
        
        # Combine
        rates = np.concatenate([r1r6_rates, r8_rates]).astype(np.float32)
        rates = np.clip(rates, 0, max_rate)
        
        return rates
    
    def get_indices(self):
        """Return neuron indices for R1-R6 and R8 populations."""
        return {
            'r1r6': slice(0, self.n_brightness),
            'r8': slice(self.n_brightness, self.n_total),
        }


class SensorAdapter:
    """High-level adapter: WoC obs → photoreceptor rates → engine input."""
    
    def __init__(self, n_brightness=3335, n_color=811):
        self.mapper = PhotoreceptorMapper(n_brightness, n_color)
        self.n_total = n_brightness + n_color
    
    def encode(self, obs, max_rate=100.0):
        """Encode WoC observation to firing rates."""
        return self.mapper.encode(obs, max_rate)
    
    def encode_batch(self, obs_batch, max_rate=100.0):
        """Encode batch of observations."""
        return np.stack([self.encode(o, max_rate) for o in obs_batch])
    
    def to_tensor(self, rates, device='cpu'):
        """Convert rates to torch tensor."""
        return torch.tensor(rates, dtype=torch.float32, device=device)


if __name__ == "__main__":
    # Test encoding
    adapter = SensorAdapter()
    
    # Simulate WoC observation
    obs = np.array([
        0.0,    # pos_x
        0.0,    # pos_z
        0.8,    # hp_frac
        1.0,    # maxHp
        0.3,    # mob_dist (30 yards)
        0.5,    # mob_type
        0.5,    # npc_dist (50 yards)
        0.3,    # npc_type
        0.5,    # time (noon)
        0.5,    # tick
        0.0,    # no quest
        0.0,    # quest id
        0.2,    # inventory
        0.0,    # copper
        0.0,    # not in combat
        0.0,    # kills
    ])
    
    rates = adapter.encode(obs)
    print(f"[sensor_adapter] Total photoreceptors: {len(rates)}")
    print(f"[sensor_adapter] R1-R6: {rates[:3335].mean():.1f} Hz (mean), {rates[:3335].max():.1f} Hz (max)")
    print(f"[sensor_adapter] R8: {rates[3335:].mean():.1f} Hz (mean), {rates[3335:].max():.1f} Hz (max)")
    print(f"[sensor_adapter] Total firing rate: {rates.sum():.0f} Hz")
