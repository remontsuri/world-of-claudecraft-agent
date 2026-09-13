"""engine.py — LIF neural simulation engine adapted from fly-brain.

Runs the full FlyWire v783 connectome (138K neurons, 15M synapses) 
on PyTorch with sparse matrix operations.
"""
import torch
import torch.nn as nn
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.fly_brain.connectome import load_connectome, build_sparse_weights


# LIF Model Parameters (from Shiu et al. / fly-brain)
MODEL_PARAMS = {
    'tauSyn': 5.0,        # ms
    'tDelay': 1.8,        # ms
    'v0': -52.0,          # mV
    'vReset': -52.0,      # mV
    'vRest': -52.0,       # mV
    'vThreshold': -45.0,  # mV
    'tauMem': 20.0,       # ms
    'tRefrac': 2.2,       # ms
    'scalePoisson': 250,
    'wScale': 0.275,
}

DT = 0.1  # Simulation timestep in ms


class PoissonSpikeGenerator(nn.Module):
    """Generates Poisson-distributed spikes from firing rates."""
    
    def __init__(self, dt=DT, scale=250, device='cpu'):
        super().__init__()
        self.prob_scale = dt / 1000.0
        self.scale = scale
        self.device = device
    
    def forward(self, rates):
        return torch.bernoulli(rates * self.prob_scale) * self.scale


class AlphaSynapse(nn.Module):
    """Alpha-function synapse dynamics with configurable delay."""
    
    def __init__(self, batch, size, dt=DT, params=MODEL_PARAMS, device='cpu'):
        super().__init__()
        self.time_factor = dt / params['tauSyn']
        self.steps_delay = int(params['tDelay'] / dt)
        self.size = size
        self.device = device
        self.batch = batch
    
    def state_init(self):
        conductance = torch.zeros(self.batch, self.size, device=self.device)
        delay_buffer = torch.zeros(
            self.batch, self.steps_delay + 1, self.size, device=self.device
        )
        return conductance, delay_buffer
    
    def forward(self, input_, conductance, delay_buffer, refrac):
        conductance_new = (
            conductance * (1 - self.time_factor) + delay_buffer[:, 0, :] * refrac
        )
        delay_buffer = torch.roll(delay_buffer, shifts=-1, dims=1)
        delay_buffer[:, -1, :] = input_
        return conductance_new, delay_buffer


class LIFNeuron(nn.Module):
    """Leaky Integrate-and-Fire neuron with surrogate gradient."""
    
    def __init__(self, batch, size, dt=DT, params=MODEL_PARAMS, device='cpu'):
        super().__init__()
        self.size = size
        self.device = device
        self.batch = batch
        self.dt = dt
        self.tau_mem = params['tauMem']
        self.v_rest = params['vRest']
        self.v_threshold = params['vThreshold']
        self.v_reset = params['vReset']
        self.tau_refrac = params['tRefrac']
        self.dt_over_tau = dt / self.tau_mem
        self.refrac_steps = int(self.tau_refrac / dt)
    
    def state_init(self):
        v = torch.full((self.batch, self.size), self.v_rest, device=self.device)
        refrac = torch.ones((self.batch, self.size), device=self.device)
        return v, refrac
    
    def forward(self, synaptic_current, v, refrac):
        # Update refractory counter: increment toward 1.0 (ready to fire)
        # refrac=1.0 means ready, refrac=0.0 means just spiked (in refractory)
        refrac = torch.clamp(refrac + self.dt / self.tau_refrac, 0, 1)
        
        # Leaky integration (always active, refractory only blocks spikes)
        v = v + self.dt_over_tau * ((self.v_rest - v) + synaptic_current)
        
        # Spike when threshold crossed AND not in refractory
        can_fire = (refrac >= 1.0).float()
        spike = (v >= self.v_threshold).float() * can_fire
        
        # Reset spiking neurons
        v = torch.where(spike > 0, torch.tensor(self.v_reset, device=self.device), v)
        
        # Set refractory to 0 for spiking neurons (they must wait tau_refrac before next spike)
        refrac = torch.where(spike > 0, torch.zeros_like(refrac), refrac)
        
        return v, spike, refrac


class AlphaLIF(nn.Module):
    """Combined AlphaSynapse + LIFNeuron."""
    
    def __init__(self, batch, size, dt=DT, params=MODEL_PARAMS, device='cpu'):
        super().__init__()
        self.synapse = AlphaSynapse(batch, size, dt, params, device)
        self.neuron = LIFNeuron(batch, size, dt, params, device)
        self.size = size
        self.device = device
        self.batch = batch
    
    def state_init(self):
        conductance, delay_buffer = self.synapse.state_init()
        v, refrac = self.neuron.state_init()
        spikes = torch.zeros(self.batch, self.size, device=self.device)
        return conductance, delay_buffer, spikes, v, refrac
    
    def forward(self, input_, conductance, delay_buffer, spikes, v, refrac):
        conductance, delay_buffer = self.synapse(input_, conductance, delay_buffer, refrac)
        v, spike, refrac = self.neuron(conductance, v, refrac)
        return conductance, delay_buffer, spike, v, refrac


class TorchModel(nn.Module):
    """Full brain model: Poisson → recurrent weights → AlphaLIF."""
    
    def __init__(self, batch, n_neurons, dt=DT, params=MODEL_PARAMS, 
                 weights=None, device='cpu'):
        super().__init__()
        self.n_neurons = n_neurons
        self.device = device
        self.batch = batch
        self.poisson = PoissonSpikeGenerator(dt, params['scalePoisson'], device)
        self.alpha_lif = AlphaLIF(batch, n_neurons, dt, params, device)
        self.weights = weights  # sparse CSR [n, n]
    
    def state_init(self):
        return self.alpha_lif.state_init()
    
    def forward(self, rates, conductance, delay_buffer, spikes, v, refrac):
        # External input spikes from rates
        input_spikes = self.poisson(rates)
        
        # Recurrent input: previous spikes @ W^T
        recurrent_input = torch.sparse.mm(self.weights.t(), spikes.t().float()).t()
        
        # Normalize: weights sum can be large, scale to reasonable current range
        # Typical input per neuron: 500 synapses * 10 Hz * 0.1ms * weight ~ 500*10*0.001*10 = 50
        # Scale factor: 1/1000 to get into mV range
        recurrent_input = recurrent_input / 1000.0
        
        # Total synaptic input = external + recurrent
        total_input = input_spikes + recurrent_input
        
        # Update LIF with total input
        conductance, delay_buffer, spikes, v, refrac = self.alpha_lif(
            total_input, conductance, delay_buffer, spikes, v, refrac
        )
        
        # DEBUG
        if torch.rand(1).item() < 0.01:
            print(f"[DEBUG] in_max={input_spikes.max().item():.1f} rec_max={recurrent_input.max().item():.1f} v_max={v.max().item():.1f} spikes={spikes.sum().item():.0f}")
        
        return conductance, delay_buffer, spikes, v, refrac
    
    def get_firing_rates(self, spikes_history, window=100):
        """Compute firing rates from spike history."""
        if len(spikes_history) == 0:
            return torch.zeros(self.batch, self.n_neurons, device=self.device)
        recent = torch.stack(spikes_history[-window:])
        return recent.sum(dim=0) / (window * DT / 1000.0)


class BrainEngine:
    """High-level interface for running the brain simulation."""
    
    def __init__(self, device='cpu', batch=1):
        self.device = device
        self.batch = batch
        self.model = None
        self.state = None
        self.spike_history = []
        self.rate_history = []
    
    def initialize(self):
        """Load connectome and initialize the model."""
        print("[engine] Loading connectome...")
        df, flyid2i, i2flyid, n_neurons = load_connectome()
        self.flyid2i = flyid2i
        self.i2flyid = i2flyid
        self.n_neurons = n_neurons
        
        print(f"[engine] Building sparse weights ({n_neurons}x{n_neurons})...")
        self.weights = build_sparse_weights(df, flyid2i, n_neurons, device=self.device)
        
        print(f"[engine] Creating TorchModel (batch={self.batch})...")
        self.model = TorchModel(
            self.batch, n_neurons, weights=self.weights, device=self.device
        )
        self.state = self.model.state_init()
        
        print(f"[engine] Ready. {n_neurons} neurons on {self.device}")
    
    def stimulate_neurons(self, neuron_indices, rate=100.0):
        """Set firing rates for specific neurons."""
        rates = torch.zeros(self.batch, self.n_neurons, device=self.device)
        if isinstance(neuron_indices, (list, np.ndarray)):
            idx = torch.tensor(neuron_indices, dtype=torch.long, device=self.device)
            rates[0, idx] = rate
        return rates
    
    def step(self, rates=None, n_steps=1):
        """Advance simulation by n_steps timesteps."""
        if rates is None:
            rates = torch.zeros(self.batch, self.n_neurons, device=self.device)
        
        conductance, delay_buffer, spikes, v, refrac = self.state
        
        total_spikes = torch.zeros(self.batch, self.n_neurons, device=self.device)
        
        for _ in range(n_steps):
            conductance, delay_buffer, spikes, v, refrac = self.model(
                rates, conductance, delay_buffer, spikes, v, refrac
            )
            total_spikes += spikes
        
        self.state = (conductance, delay_buffer, spikes, v, refrac)
        self.spike_history.append(total_spikes.detach())
        
        # Keep history bounded
        if len(self.spike_history) > 1000:
            self.spike_history = self.spike_history[-500:]
        
        return total_spikes
    
    def get_firing_rates(self, window=100):
        """Get recent firing rates."""
        if len(self.spike_history) == 0:
            return torch.zeros(self.batch, self.n_neurons, device=self.device)
        recent = torch.stack(self.spike_history[-window:])
        return recent.sum(dim=0) / (window * DT / 1000.0)
    
    def stimulate_and_step(self, neuron_indices, rate=100.0, n_steps=10):
        """Convenience: stimulate neurons and step."""
        rates = self.stimulate_neurons(neuron_indices, rate)
        spikes = self.step(rates, n_steps)
        return spikes


if __name__ == "__main__":
    engine = BrainEngine(device='cpu', batch=1)
    engine.initialize()
    
    # Test: stimulate random neurons and run 500+ steps (delay is 1.8ms = 18 steps)
    print("\n[engine] Running test simulation (500 steps)...")
    random_neurons = np.random.choice(engine.n_neurons, size=500, replace=False).tolist()
    
    for i in range(50):
        rates = engine.stimulate_neurons(random_neurons, rate=500.0)
        spikes = engine.step(rates, n_steps=10)
        if (i+1) % 10 == 0:
            v = engine.state[3].max().item() if engine.state[3].numel() > 0 else 0
            total = spikes.sum().item()
            print(f"  Step {i+1}: {total:.0f} spikes, v_max={v:.1f}")
    
    print("\n[engine] Test complete.")
