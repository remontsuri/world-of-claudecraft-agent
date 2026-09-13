"""engine.py — LIF neural simulation engine for FAFB 138K (sparse).

Optimized for ROCm/CUDA. Uses sparse matrix multiplication for recurrent connections.
"""
import torch
import torch.nn as nn
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# LIF Model Parameters (from Shiu et al. / fly-brain)
MODEL_PARAMS = {
    'tauSyn': 5.0,        # ms
    'tDelay': 1.8,        # ms
    'v0': -65.0,          # mV
    'vReset': -65.0,      # mV
    'vRest': -65.0,       # mV
    'vThreshold': -50.0,  # mV
    'tauMem': 10.0,       # ms
    'tRefrac': 2.0,       # ms
    'scalePoisson': 100,
    'wScale': 0.1,
}

DT = 0.2  # Simulation timestep in ms

def get_device():
    """Get best available device."""
    if torch.cuda.is_available():
        print(f"[engine] Using GPU: {torch.cuda.get_device_name(0)}")
        return 'cuda'
    try:
        import torch_directml
        if torch_directml.is_available():
            return torch_directml.device()
    except ImportError:
        pass
    print("[engine] Using CPU")
    return 'cpu'


def load_sparse_from_parquet(parquet_path='D:/fly-brain/data/2025_Connectivity_783.parquet'):
    """Load FlyWire FAFB v783 connectivity and build sparse tensor."""
    import pandas as pd
    
    df = pd.read_parquet(parquet_path)
    
    all_ids = pd.concat([df["Presynaptic_ID"], df["Postsynaptic_ID"]]).unique()
    all_ids.sort()
    
    flyid2i = {fid: i for i, fid in enumerate(all_ids)}
    n_neurons = len(all_ids)
    
    pre_idx = df["Presynaptic_ID"].map(flyid2i).values.astype(np.int64)
    post_idx = df["Postsynaptic_ID"].map(flyid2i).values.astype(np.int64)
    weights = df["Connectivity"].values.astype(np.float32) * MODEL_PARAMS['wScale']
    
    # W[post, pre] = weight
    indices = torch.tensor(np.stack([post_idx, pre_idx]), dtype=torch.long)
    values = torch.tensor(weights, dtype=torch.float32)
    
    W = torch.sparse_coo_tensor(indices, values, (n_neurons, n_neurons)).coalesce()
    
    print(f"[connectome] FAFB: {n_neurons} neurons, {len(weights)} synapses")
    return W, n_neurons


class PoissonSpikeGenerator(nn.Module):
    def __init__(self, dt=DT, scale=100):
        super().__init__()
        self.prob_scale = dt / 1000.0
        self.scale = scale
    
    def forward(self, rates):
        return torch.bernoulli(rates * self.prob_scale) * self.scale


class AlphaSynapse(nn.Module):
    def __init__(self, n_neurons, dt=DT, params=MODEL_PARAMS):
        super().__init__()
        self.time_factor = dt / params['tauSyn']
        self.steps_delay = int(params['tDelay'] / dt) + 1
        self.n_neurons = n_neurons
    
    def state_init(self, batch, device):
        conductance = torch.zeros(batch, self.n_neurons, device=device)
        delay_buffer = torch.zeros(batch, self.steps_delay, self.n_neurons, device=device)
        return conductance, delay_buffer
    
    def forward(self, input_, conductance, delay_buffer, refrac):
        conductance_new = conductance * (1 - self.time_factor) + delay_buffer[:, 0, :] * refrac
        delay_buffer = torch.cat([delay_buffer[:, 1:, :], input_.unsqueeze(1)], dim=1)
        return conductance_new, delay_buffer


class LIFNeuron(nn.Module):
    def __init__(self, n_neurons, dt=DT, params=MODEL_PARAMS):
        super().__init__()
        self.n_neurons = n_neurons
        self.dt = dt
        self.tau_mem = params['tauMem']
        self.v_rest = params['vRest']
        self.v_threshold = params['vThreshold']
        self.v_reset = params['vReset']
        self.tau_refrac = params['tRefrac']
        self.dt_over_tau = dt / self.tau_mem
    
    def state_init(self, batch, device):
        v = torch.full((batch, self.n_neurons), self.v_rest, device=device)
        refrac = torch.ones(batch, self.n_neurons, device=device)
        return v, refrac
    
    def forward(self, synaptic_current, v, refrac):
        refrac = torch.clamp(refrac + self.dt / self.tau_refrac, 0, 1)
        v = v + self.dt_over_tau * ((self.v_rest - v) + synaptic_current)
        can_fire = (refrac >= 1.0).float()
        spike = (v >= self.v_threshold).float() * can_fire
        v = torch.where(spike > 0, torch.full_like(v, self.v_reset), v)
        refrac = torch.where(spike > 0, torch.zeros_like(refrac), refrac)
        return v, spike, refrac


class SparseLIFModel(nn.Module):
    """Full brain model: Poisson → sparse recurrent weights → LIF."""
    
    def __init__(self, n_neurons, dt=DT, params=MODEL_PARAMS, weights=None):
        super().__init__()
        self.n_neurons = n_neurons
        self.dt = dt
        self.poisson = PoissonSpikeGenerator(dt, params['scalePoisson'])
        self.synapse = AlphaSynapse(n_neurons, dt, params)
        self.neuron = LIFNeuron(n_neurons, dt, params)
        self.weights = weights  # sparse [n, n]
    
    def state_init(self, batch, device):
        conductance, delay_buffer = self.synapse.state_init(batch, device)
        v, refrac = self.neuron.state_init(batch, device)
        return conductance, delay_buffer, v, refrac
    
    def forward(self, rates, conductance, delay_buffer, v, refrac):
        input_spikes = self.poisson(rates)
        
        # Recurrent input: W @ input_spikes (sparse)
        recurrent_input = torch.sparse.mm(self.weights, input_spikes.t()).t()
        
        # Update LIF
        conductance, delay_buffer = self.synapse(input_spikes, conductance, delay_buffer, refrac)
        v, spike, refrac = self.neuron(conductance, v, refrac)
        
        return conductance, delay_buffer, v, refrac, spike


class BrainEngine:
    def __init__(self, device=None, batch=1):
        self.device = device or get_device()
        self.batch = batch
        self.model = None
        self.state = None
        self.spike_history = []
    
    def initialize(self, W_sparse=None, n_neurons=None):
        print("[engine] Loading connectome...")
        
        if W_sparse is None:
            W_sparse, n_neurons = load_sparse_from_parquet()
        
        self.n_neurons = n_neurons
        self.W_sparse = W_sparse.to(self.device)
        
        print(f"[engine] Creating SparseLIFModel ({n_neurons} neurons, device={self.device})...")
        self.model = SparseLIFModel(n_neurons, weights=self.W_sparse)
        self.state = self.model.state_init(self.batch, self.device)
        
        print(f"[engine] Ready. {n_neurons} neurons on {self.device}")
    
    def step(self, rates=None, n_steps=1):
        if rates is None:
            rates = torch.zeros(self.batch, self.n_neurons, device=self.device)
        
        conductance, delay_buffer, v, refrac = self.state
        
        total_spikes = torch.zeros(self.batch, self.n_neurons, device=self.device)
        
        for _ in range(n_steps):
            conductance, delay_buffer, v, refrac, spike = self.model(
                rates, conductance, delay_buffer, v, refrac
            )
            total_spikes += spike
        
        self.state = (conductance, delay_buffer, v, refrac)
        self.spike_history.append(total_spikes.detach())
        
        if len(self.spike_history) > 1000:
            self.spike_history = self.spike_history[-500:]
        
        return total_spikes
    
    def stimulate_neurons(self, neuron_indices, rate=100.0):
        rates = torch.zeros(self.batch, self.n_neurons, device=self.device)
        if isinstance(neuron_indices, (list, np.ndarray)):
            idx = torch.tensor(neuron_indices, dtype=torch.long, device=self.device)
            rates[0, idx] = rate
        return rates
    
    def get_firing_rates(self, window=100):
        if len(self.spike_history) == 0:
            return torch.zeros(self.batch, self.n_neurons, device=self.device)
        recent = torch.stack(self.spike_history[-window:])
        return recent.sum(dim=0) / (window * DT / 1000.0)


if __name__ == "__main__":
    engine = BrainEngine()
    engine.initialize()
    
    print(f"\n[engine] Running test simulation (100 steps)...")
    random_neurons = np.random.choice(engine.n_neurons, size=500, replace=False).tolist()
    
    for i in range(10):
        rates = engine.stimulate_neurons(random_neurons, rate=150.0)
        spikes = engine.step(rates, n_steps=10)
        if (i+1) % 5 == 0:
            v = engine.state[2].max().item()
            total = spikes.sum().item()
            print(f"  Step {i+1}: {total:.0f} spikes, v_max={v:.1f}")
    
    print("\n[engine] Test complete.")
