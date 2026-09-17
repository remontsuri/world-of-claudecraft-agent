"""da_stdp.py — dopamine-modulated STDP for KC→MBON plasticity.

Implements DA-STDP learning rule:
    ΔW = η · DA(t) · exp(-|Δt|/τ) · Sign(Δt)

Where:
- DA(t) = dopamine concentration (from PPL101/PAM activation)
- Δt = t_post - t_pre (spike timing difference)
- τ = STDP time constant
- η = learning rate

Positive events (kill, quest, loot) → PAM activation → LTP
Negative events (damage, death) → PPL101 activation → LTD
"""
import numpy as np
import torch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class DopamineModulatedSTDP:
    """DA-STDP learning for KC→MBON synapses."""
    
    def __init__(self, n_kc=4133, n_mbon=96, tau_stdp=20.0, eta=0.001, 
                 da_tau=100.0, device=None):
        """
        n_kc: number of Kenyon cells
        n_mbon: number of MB output neurons
        tau_stdp: STDP time constant (ms)
        eta: learning rate
        da_tau: dopamine decay time constant (ms)
        """
        self.n_kc = n_kc
        self.n_mbon = n_mbon
        self.tau_stdp = tau_stdp
        self.eta = eta
        self.da_tau = da_tau
        if device is None:                      # было 'cpu': STDP-веса уезжали на CPU
            from src.fly_brain.engine import get_device
            device = get_device()
        self.device = device
        
        # KC→MBON weights (sparse)
        self.weights = torch.zeros(n_kc, n_mbon, device=device)
        
        # Initialize with small random weights
        self.weights = torch.rand(n_kc, n_mbon, device=device) * 0.1
        
        # Dopamine level (decays over time)
        self.da_level = 0.0
        
        # Spike history for STDP
        self.kc_spike_times = []  # (time, neuron_idx)
        self.mbon_spike_times = []
        
        self.t = 0  # current time in ms
    
    def set_weights_from_connectome(self, weights):
        """Initialize weights from connectome data."""
        if weights.shape == (self.n_kc, self.n_mbon):
            self.weights = weights.to(self.device)
        else:
            print(f"[DA-STDP] Warning: weight shape mismatch {weights.shape} vs {(self.n_kc, self.n_mbon)}")
    
    def release_dopamine(self, amount, duration_ms=100):
        """Release dopamine (from PAM or PPL101 activation)."""
        self.da_level += amount
    
    def decay_dopamine(self, dt_ms):
        """Exponential dopamine decay."""
        self.da_level *= np.exp(-dt_ms / self.da_tau)
    
    def process_event(self, event_type, dt_ms=0.1):
        """Process game event and release dopamine accordingly.
        
        event_type: 'damage', 'death', 'kill', 'quest_complete', 'loot'
        """
        self.t += dt_ms
        self.decay_dopamine(dt_ms)
        
        if event_type in ('damage', 'death'):
            # Negative event → PPL101 activation → LTD
            # Stronger for death
            amount = 2.0 if event_type == 'death' else 1.0
            self.release_dopamine(amount)
            return -amount  # negative signal
        
        elif event_type in ('kill', 'quest_complete', 'loot'):
            # Positive event → PAM activation → LTP
            amount = 1.5 if event_type == 'kill' else 2.0 if event_type == 'quest_complete' else 1.0
            self.release_dopamine(amount)
            return amount  # positive signal
        
        return 0.0
    
    def update(self, kc_spikes, mbon_spikes, dt_ms=0.1):
        """Update weights using DA-STDP rule.
        
        kc_spikes: binary tensor of shape (n_kc,) — KC spikes at current timestep
        mbon_spikes: binary tensor of shape (n_mbon,) — MBON spikes
        dt_ms: timestep duration
        """
        if isinstance(kc_spikes, np.ndarray):
            kc_spikes = torch.tensor(kc_spikes, dtype=torch.float32, device=self.device)
        if isinstance(mbon_spikes, np.ndarray):
            mbon_spikes = torch.tensor(mbon_spikes, dtype=torch.float32, device=self.device)
        
        # Record spike times
        kc_active = (kc_spikes > 0).nonzero(as_tuple=True)[0]
        mbon_active = (mbon_spikes > 0).nonzero(as_tuple=True)[0]
        
        for idx in kc_active:
            self.kc_spike_times.append((self.t, idx.item()))
        for idx in mbon_active:
            self.mbon_spike_times.append((self.t, idx.item()))
        
        # Keep history bounded (last 1000 spikes each)
        if len(self.kc_spike_times) > 1000:
            self.kc_spike_times = self.kc_spike_times[-500:]
        if len(self.mbon_spike_times) > 1000:
            self.mbon_spike_times = self.mbon_spike_times[-500:]
        
        # Compute STDP updates
        if self.da_level < 0.01:
            return 0.0  # no dopamine, no learning
        
        weight_change = 0.0
        
        # For each recent KC spike, find nearby MBON spikes
        for t_kc, kc_idx in self.kc_spike_times[-100:]:
            for t_mbon, mbon_idx in self.mbon_spike_times[-100:]:
                dt = t_mbon - t_kc  # post - pre
                
                if abs(dt) > 5 * self.tau_stdp:
                    continue  # too far apart
                
                # STDP kernel
                stdp = np.exp(-abs(dt) / self.tau_stdp) * np.sign(dt)
                
                # DA-STDP update
                delta_w = self.eta * self.da_level * stdp
                
                # Apply
                self.weights[kc_idx, mbon_idx] += delta_w
                weight_change += abs(delta_w)
        
        # Clip weights to [0, 1]
        self.weights = torch.clamp(self.weights, 0, 1)
        
        return weight_change
    
    def get_weight_stats(self):
        """Get statistics about KC→MBON weights."""
        return {
            'mean': self.weights.mean().item(),
            'std': self.weights.std().item(),
            'max': self.weights.max().item(),
            'min': self.weights.min().item(),
            'sparsity': (self.weights < 0.01).float().mean().item(),
        }


if __name__ == "__main__":
    stdp = DopamineModulatedSTDP(n_kc=100, n_mbon=20)  # small for testing
    
    # Simulate learning
    rng = np.random.RandomState(42)
    
    for step in range(100):
        kc_spikes = rng.poisson(0.1, 100).astype(np.float32)
        mbon_spikes = rng.poisson(0.05, 20).astype(np.float32)
        
        # Simulate events
        if step == 30:
            stdp.process_event('damage')
        elif step == 60:
            stdp.process_event('kill')
        
        weight_change = stdp.update(kc_spikes, mbon_spikes)
        
        if step % 20 == 0:
            stats = stdp.get_weight_stats()
            print(f"  Step {step}: DA={stdp.da_level:.2f}, ΔW={weight_change:.4f}, "
                  f"mean={stats['mean']:.3f}, std={stats['std']:.3f}")
    
    print(f"\n[DA-STDP] Final stats: {stdp.get_weight_stats()}")
