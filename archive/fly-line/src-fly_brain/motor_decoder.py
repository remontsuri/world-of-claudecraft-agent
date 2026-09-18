"""motor_decoder.py — decode descending neuron spikes to WoC actions via WTA.

Hard-coded readout channels (from baseline noise test, FAFB v783):
- Neuron 105779 (5.0 Hz) → DNg13_LEFT  → TURN_LEFT  (2)
- Neuron 79732  (5.0 Hz) → DNg13_RIGHT → TURN_RIGHT (1)
- Neuron 123853 (5.0 Hz) → GiantFiber   → ATTACK     (3)
- Neuron 37567  (5.0 Hz) → CentralComplex → TARGET  (4)
- Neuron 130107 (5.0 Hz) → VNC_Mech   → LOOT_QUEST (5)
- Both DNg13 active simultaneously → MOVE_FORWARD (0)
- No activity → REST (6)
"""
import numpy as np
import torch


class FixedThresholdDecoder:
    """Decode spikes using fixed threshold on specific readout neurons.
    
    Threshold = S_base + 20% (from baseline noise measurement).
    Baseline = 0 Hz, so threshold ≈ 0.1 Hz (any spike = action).
    """
    
    ACTION_NAMES = {
        0: 'MOVE_FORWARD',
        1: 'TURN_LEFT',
        2: 'TURN_RIGHT',
        3: 'ATTACK',
        4: 'TARGET_NEAREST',
        5: 'LOOT_QUEST',
        6: 'REST',
    }
    
    # Readout neuron indices (from baseline noise test)
    READOUT = {
        'DNg13_LEFT': 105779,
        'DNg13_RIGHT': 79732,
        'GF': 123853,
        'CC': 37567,
        'VNC': 130107,
    }
    
    def __init__(self, threshold=0.1, cooldown=5):
        """
        threshold: Hz, minimum firing rate to trigger action
        cooldown: minimum steps between actions
        """
        self.threshold = threshold
        self.cooldown = cooldown
        self.steps_since_action = cooldown  # ready immediately
        self.last_action = 6  # REST
        self.group_rates = {k: 0.0 for k in self.READOUT}
        
    def update_rates(self, spike_counts, window_steps, dt_ms=0.1):
        """Update group rates from spike counts."""
        duration_s = window_steps * dt_ms / 1000.0
        for name, idx in self.READOUT.items():
            self.group_rates[name] = spike_counts[idx] / duration_s if duration_s > 0 else 0.0
        self.steps_since_action += 1
    
    def decode(self, spikes=None, n_steps=1, dt_ms=0.1):
        """Decode spikes to action with fixed threshold and cooldown.
        
        Returns: action_id (0-6)
        """
        if spikes is not None:
            if isinstance(spikes, torch.Tensor):
                spikes = spikes.detach().cpu().numpy().reshape(-1)
            spike_counts = spikes
            self.update_rates(spike_counts, n_steps, dt_ms)
        
        # Cooldown check
        if self.steps_since_action < self.cooldown:
            return self.last_action
        
        # Check thresholds
        l = self.group_rates['DNg13_LEFT']
        r = self.group_rates['DNg13_RIGHT']
        gf = self.group_rates['GF']
        cc = self.group_rates['CC']
        vnc = self.group_rates['VNC']
        
        action = 6  # REST by default
        
        # Both DNg13 active → MOVE_FORWARD
        if l > self.threshold and r > self.threshold:
            action = 0
        # Left only → TURN_LEFT
        elif l > self.threshold and l > r:
            action = 2
        # Right only → TURN_RIGHT
        elif r > self.threshold and r > l:
            action = 1
        # Giant Fiber → ATTACK
        elif gf > self.threshold:
            action = 3
        # Central Complex → TARGET
        elif cc > self.threshold:
            action = 4
        # VNC Mechanosensory → LOOT_QUEST
        elif vnc > self.threshold:
            action = 5
        
        self.last_action = action
        if action != 6:
            self.steps_since_action = 0
        
        return action
    
    def get_action_name(self, action_id):
        return self.ACTION_NAMES.get(action_id, 'UNKNOWN')


class WinnerTakeAll:
    """Lateral inhibition WTA circuit (kept for reference/compat)."""
    
    def __init__(self, n_groups, inhibition_strength=0.8):
        self.n_groups = n_groups
        self.inhibition_strength = inhibition_strength
    
    def select(self, rates):
        if len(rates) == 0:
            return 0
        rates = np.asarray(rates, dtype=np.float32)
        rates = rates + np.random.uniform(0, 0.01, len(rates))
        winner = np.argmax(rates)
        return int(winner)


# Backwards compat
MotorDecoder = FixedThresholdDecoder


if __name__ == "__main__":
    decoder = FixedThresholdDecoder(threshold=0.1, cooldown=3)
    
    # Test with baseline (no spikes)
    spikes_zero = np.zeros(138639)
    action = decoder.decode(spikes_zero, n_steps=10)
    print(f'Baseline: action={action} ({decoder.get_action_name(action)})')
    
    # Test with DNg13_LEFT active
    spikes_left = np.zeros(138639)
    spikes_left[105779] = 5  # 5 spikes in 10 steps = 50 Hz
    action = decoder.decode(spikes_left, n_steps=10)
    print(f'DNg13_LEFT active: action={action} ({decoder.get_action_name(action)})')
    
    # Test with GF active
    spikes_gf = np.zeros(138639)
    spikes_gf[123853] = 10
    action = decoder.decode(spikes_gf, n_steps=10)
    print(f'GF active: action={action} ({decoder.get_action_name(action)})')
    
    # Test with both DNg13
    spikes_both = np.zeros(138639)
    spikes_both[105779] = 5
    spikes_both[79732] = 5
    action = decoder.decode(spikes_both, n_steps=10)
    print(f'Both DNg13: action={action} ({decoder.get_action_name(action)})')
    
    print('[motor_decoder] FixedThresholdDecoder OK')
