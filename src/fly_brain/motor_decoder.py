"""motor_decoder.py — decode descending neuron spikes to WoC actions via WTA.

Maps specific descending neuron groups to discrete game actions:
- DNg13 (symmetric L+R) → MOVE_FORWARD (0)
- DNg13 (asymmetry R>L) → TURN_LEFT (1)
- DNg13 (asymmetry L>R) → TURN_RIGHT (2)
- Giant Fiber (GF) → ATTACK (3)
- Central Complex (Eb/Pb) → TARGET_NEAREST (4)
- VNC_Mechanosensory → LOOT/QUEST (5)
- Quiescent/PAM → REST (6)
"""
import numpy as np
import torch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class WinnerTakeAll:
    """Lateral inhibition WTA circuit."""
    
    def __init__(self, n_groups, inhibition_strength=0.8):
        self.n_groups = n_groups
        self.inhibition_strength = inhibition_strength
    
    def select(self, rates):
        """Select winning group via lateral inhibition.
        
        rates: array of shape (n_groups,) firing rates
        
        Returns: selected group index
        """
        if len(rates) == 0:
            return 0
        
        rates = np.asarray(rates, dtype=np.float32)
        
        # Add small noise to break ties
        rates = rates + np.random.uniform(0, 0.01, len(rates))
        
        # Winner-take-all: highest rate wins
        winner = np.argmax(rates)
        
        # Apply inhibition (for analysis/debugging)
        inhibited = rates.copy()
        for i in range(len(rates)):
            if i != winner:
                inhibited[i] *= (1 - self.inhibition_strength)
        
        return winner


class MotorDecoder:
    """Decode DN spikes to discrete WoC actions.
    
    Reads firing rates from predefined descending neuron groups
    and applies WTA to select the action.
    """
    
    # Action mapping
    ACTION_NAMES = {
        0: 'MOVE_FORWARD',
        1: 'TURN_LEFT',
        2: 'TURN_RIGHT',
        3: 'ATTACK',
        4: 'TARGET_NEAREST',
        5: 'LOOT_QUEST',
        6: 'REST',
    }
    
    def __init__(self, n_neurons, groups=None, window=50, dt=0.1):
        """
        n_neurons: total neurons in brain
        groups: dict mapping action_id -> list of neuron indices
        window: spike history window for rate computation
        dt: timestep in ms
        """
        self.n_neurons = n_neurons
        self.window = window
        self.dt = dt
        
        # Default DN groups (anatomically inspired)
        if groups is None:
            groups = self._default_groups(n_neurons)
        self.groups = groups
        
        self.wta = WinnerTakeAll(len(groups))
        self.spike_history = []
        
        # Baseline rates for each group
        self.baselines = {aid: 0.0 for aid in self.groups}
    
    def _default_groups(self, n_neurons):
        """Create default descending neuron groups."""
        rng = np.random.RandomState(42)
        
        # Distribute DNs across the neuron population (VNC neurons tend to be posterior)
        # For now, use random assignment in posterior third of neurons
        vnc_start = int(n_neurons * 0.7)
        vnc_neurons = np.arange(vnc_start, n_neurons)
        
        groups = {}
        n_per_group = len(vnc_neurons) // 7
        
        for aid in range(7):
            start = aid * n_per_group
            end = start + n_per_group if aid < 6 else len(vnc_neurons)
            groups[aid] = vnc_neurons[start:end].tolist()
        
        return groups
    
    def add_spikes(self, spikes):
        """Add spike observation to history."""
        if isinstance(spikes, torch.Tensor):
            spikes = spikes.detach().cpu().numpy()
        self.spike_history.append(spikes.reshape(-1))
        
        # Keep bounded
        if len(self.spike_history) > 1000:
            self.spike_history = self.spike_history[-500:]
    
    def get_group_rates(self):
        """Compute firing rates for each DN group."""
        if len(self.spike_history) == 0:
            return {aid: 0.0 for aid in self.groups}
        
        # Use recent window
        recent = np.stack(self.spike_history[-self.window:])
        # Sum over time, divide by window duration in seconds
        spike_counts = recent.sum(axis=0)
        duration_s = self.window * self.dt / 1000.0
        rates = spike_counts / duration_s  # Hz
        
        # Compute mean rate per group
        group_rates = {}
        for aid, indices in self.groups.items():
            group_rates[aid] = float(np.mean(rates[indices]))
        
        return group_rates
    
    def decode(self, spikes=None):
        """Decode spikes to action.
        
        Returns: action_id (0-6)
        """
        if spikes is not None:
            self.add_spikes(spikes)
        
        group_rates = self.get_group_rates()
        
        # Apply WTA
        rates_array = np.array([group_rates[aid] for aid in range(7)])
        action = self.wta.select(rates_array)
        
        return int(action)
    
    def decode_batch(self, spikes_batch):
        """Decode batch of spike observations."""
        actions = []
        for spikes in spikes_batch:
            actions.append(self.decode(spikes))
        return actions
    
    def get_action_confidence(self):
        """Get confidence of current action selection."""
        group_rates = self.get_group_rates()
        rates = np.array([group_rates[aid] for aid in range(7)])
        if rates.sum() == 0:
            return 0.0
        return float(rates.max() / rates.sum())


if __name__ == "__main__":
    # Test
    n_neurons = 138639
    decoder = MotorDecoder(n_neurons)
    
    # Simulate random spikes
    rng = np.random.RandomState(42)
    
    for step in range(100):
        spikes = rng.poisson(0.1, n_neurons).astype(np.float32)
        action = decoder.decode(spikes)
        if step % 20 == 0:
            rates = decoder.get_group_rates()
            print(f"  Step {step}: action={action} ({decoder.ACTION_NAMES[action]}), "
                  f"rates={[f'{rates[a]:.1f}' for a in range(3)]}")
    
    print(f"\n[motor_decoder] Confidence: {decoder.get_action_confidence():.3f}")
