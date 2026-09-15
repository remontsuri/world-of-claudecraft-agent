"""engine.py — LIF neural simulation engine for MaleCNS v1.0.

Optimized for ROCm/CUDA. Uses sparse matrix multiplication for recurrent connections.
Supports MaleCNS v1.0 (211K neurons, 151M synapses) with neurotransmitter data.
"""
import torch
import torch.nn as nn
import numpy as np
from pathlib import Path


def get_device():
    """Get best available device."""
    if torch.cuda.is_available():
        device_name = torch.cuda.get_device_name(0)
        if 'AMD' in device_name or 'Radeon' in device_name:
            print(f"[engine] Using ROCm: {device_name}")
        return 'cuda'
    return 'cpu'


def load_sparse_weights(parquet_path='D:/fly-brain/data/2025_Connectivity_783.parquet'):
    """Load FlyWire FAFB v783 connectivity (legacy, for testing)."""
    import pandas as pd
    
    df = pd.read_parquet(parquet_path)
    print(f"[connectome] FAFB: {df['Postsynaptic_Index'].nunique()} neurons, {len(df)} synapses")
    
    rows = df['Presynaptic_Index'].values
    cols = df['Postsynaptic_Index'].values
    values = df['Connectivity'].values.astype(np.float32)
    n_neurons = df['Postsynaptic_Index'].nunique()
    
    indices = torch.tensor(np.array([rows, cols]), dtype=torch.long)
    values = torch.tensor(values, dtype=torch.float32)
    
    W = torch.sparse_coo_tensor(indices, values, (n_neurons, n_neurons)).coalesce()
    return W, n_neurons


def load_male_cns_weights(data_dir='D:/world-of-claudecraft/data/male_cns'):
    """Load MaleCNS v1.0 connectivity (151M synapses, 211K neurons)."""
    import pyarrow.feather as ft
    
    print("[connectome] Loading MaleCNS v1.0 weights...")
    
    # Load annotations for bodyId mapping
    annotations = ft.read_table(f'{data_dir}/body-annotations.feather').to_pandas()
    body2idx = dict(zip(annotations['bodyId'], range(len(annotations))))
    n_neurons = len(annotations)
    
    # Load weights in chunks
    weights_file = f'{data_dir}/connectome-weights.feather'
    
    # Check if file exists
    if not Path(weights_file).exists():
        print(f"[connectome] Weights file not found at {weights_file}")
        print("[connectome] Falling back to FAFB v783")
        return load_sparse_weights()
    
    try:
        # Try reading first chunk to check format
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(weights_file)
        total_rows = pf.metadata.num_rows
        print(f"[connectome] MaleCNS: {total_rows} connections")
    except:
        # Feather format
        import pyarrow.feather as ft
        table = ft.read_table(weights_file)
        total_rows = table.num_rows
        print(f"[connectome] MaleCNS: {total_rows} connections")
    
    # Build sparse matrix in chunks
    chunk_size = 5_000_000
    rows_list, cols_list, vals_list = [], [], []
    
    for i in range(0, total_rows, chunk_size):
        # Read chunk
        chunk = ft.read_table(weights_file).slice(i, min(chunk_size, total_rows - i)).to_pandas()
        
        # Map body IDs to indices
        pre_idx = [body2idx.get(b) for b in chunk['body_pre']]
        post_idx = [body2idx.get(b) for b in chunk['body_post']]
        
        # Filter valid
        valid = [(p, q, w) for p, q, w in zip(pre_idx, post_idx, chunk['weight']) 
                 if p is not None and q is not None]
        
        if valid:
            p, q, w = zip(*valid)
            rows_list.extend(p)
            cols_list.extend(q)
            vals_list.extend(w)
        
        if (i // chunk_size) % 10 == 0:
            print(f"  Processed {i + len(chunk)}/{total_rows}")
    
    # Create sparse tensor
    indices = torch.tensor([rows_list, cols_list], dtype=torch.long)
    values = torch.tensor(vals_list, dtype=torch.float32)
    
    W = torch.sparse_coo_tensor(indices, values, (n_neurons, n_neurons)).coalesce()
    print(f"[connectome] Sparse matrix: {W._nnz()} synapses")
    
    return W, n_neurons


def load_male_cns_weights(data_dir='D:/world-of-claudecraft/data/male_cns'):
    """Load cached MaleCNS v1.0 sparse matrix (211K neurons, 26M mapped synapses).

    Cache built by build_malecns_cache.py from connectome-weights feather.
    """
    cache = Path(data_dir) / 'male_cns_sparse.pt'
    if not cache.exists():
        print("[connectome] MaleCNS cache missing — building it now (takes ~1 min)...")
        import subprocess, sys
        subprocess.run([sys.executable, 'build_malecns_cache.py'], check=True,
                       cwd='D:/world-of-claudecraft')
        print("[connectome] Cache built.")

    print("[connectome] Loading MaleCNS v1.0 sparse matrix...")
    data = torch.load(cache, weights_only=False)
    indices = data['W_indices']
    values = data['W_values']
    n = data['n']

    W = torch.sparse_coo_tensor(indices, values, (n, n)).coalesce()
    print(f"[connectome] MaleCNS: {n} neurons, {W._nnz()} synapses")
    return W, n


# Default to MaleCNS v1.0 (official male connectome, replaces FAFB v783)
def load_connectome():
    try:
        return load_male_cns_weights()
    except Exception as e:
        print(f"[connectome] MaleCNS load failed ({e}), falling back to FAFB v783")
        return load_sparse_weights()


class BrainEngine:
    """LIF brain simulation engine."""
    
    def __init__(self, device=None, batch=1):
        self.device = device or get_device()
        self.batch = batch
        self.model = None
        self.state = None
        self.spike_history = []
        self.n_neurons = None
        self.body2idx = None  # bodyId → engine index mapping
    
    def initialize(self, W_sparse=None, n_neurons=None, body2idx=None):
        """Initialize brain with connectivity.
        
        body2idx: dict bodyId → engine index (for DN readout by bodyId)
        """
        print("[engine] Loading connectome...")
        
        if W_sparse is None:
            W_sparse, n_neurons = load_sparse_weights()
        
        self.n_neurons = n_neurons
        self.body2idx = body2idx or {}
        self.W_sparse = W_sparse.to(self.device)
        
        print(f"[engine] Creating SparseLIFModel ({n_neurons} neurons, device={self.device})...")
        self.model = SparseLIFModel(n_neurons, weights=self.W_sparse)
        self.state = self.model.state_init(self.batch, self.device)
        
        print(f"[engine] Ready. {n_neurons} neurons on {self.device}")
    
    def get_dn_indices(self, body_ids):
        """Resolve bodyIds → engine indices using body2idx mapping.
        
        Returns indices for body_ids found in mapping; skips unknown bodies.
        """
        indices = []
        for bid in body_ids:
            idx = self.body2idx.get(bid) if self.body2idx else None
            if idx is not None and idx < self.n_neurons:
                indices.append(idx)
            else:
                print(f"[engine] WARN: bodyId {bid} not in mapping")
        return indices
    
    def get_dn_rates(self, dn_indices, window=5):
        """Compute firing rates for DN neurons over recent spike history.
        
        dn_indices: list of neuron indices to read
        returns: (batch, len(dn_indices)) firing rates in Hz
        """
        if not self.spike_history:
            return torch.zeros(self.batch, len(dn_indices), device=self.device)
        recent = self.spike_history[-window:]
        total = torch.stack(recent, dim=0).sum(dim=0)  # (batch, n_neurons)
        duration_s = max(len(recent) * self.model.dt / 1000.0, 1e-6)
        rates = total / duration_s
        return rates[:, dn_indices]
    
    def step(self, rates=None, n_steps=1):
        """Step simulation."""
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
        """Stimulate specific neurons."""
        rates = torch.zeros(self.batch, self.n_neurons, device=self.device)
        if isinstance(neuron_indices, (list, np.ndarray)):
            rates[0, neuron_indices] = float(rate)
        return rates


class PoissonSpikeGenerator(nn.Module):
    """Poisson spike generator."""
    
    def __init__(self, dt=0.1, scale=250):
        super().__init__()
        self.dt = dt
        self.prob_scale = dt / 1000.0
    
    def forward(self, rates):
        return torch.bernoulli(rates * self.prob_scale) * 250.0


class AlphaSynapse(nn.Module):
    """Alpha synapse model."""
    
    def __init__(self, n_neurons, dt=0.1, tau_syn=5.0, t_delay=1.8):
        super().__init__()
        self.n_neurons = n_neurons
        self.time_factor = dt / tau_syn
        self.steps_delay = int(t_delay / dt) + 1
    
    def state_init(self, batch, device):
        conductance = torch.zeros(batch, self.n_neurons, device=device)
        delay_buffer = torch.zeros(batch, self.steps_delay, self.n_neurons, device=device)
        return conductance, delay_buffer
    
    def forward(self, input_spikes, recurrent_input, conductance, delay_buffer, refrac):
        total_input = input_spikes + recurrent_input
        conductance_new = conductance * (1 - self.time_factor) + delay_buffer[:, 0, :] * refrac
        delay_buffer = torch.cat([delay_buffer[:, 1:, :], total_input.unsqueeze(1)], dim=1)
        return conductance_new, delay_buffer


class LIFNeuron(nn.Module):
    """LIF neuron."""
    
    def __init__(self, n_neurons, dt=0.1, v_th=-45.0, v_rest=-52.0, 
                 tau_memb=20.0, t_refrac=2.2):
        super().__init__()
        self.n_neurons = n_neurons
        self.v_th = v_th
        self.v_rest = v_rest
        self.dt_over_tau = dt / tau_memb
        self.t_refrac = t_refrac
    
    def state_init(self, batch, device):
        v = torch.full((batch, self.n_neurons), self.v_rest, device=device)
        refrac = torch.ones(batch, self.n_neurons, device=device)
        return v, refrac
    
    def forward(self, conductance, v, refrac):
        active = (refrac >= 1.0).float()
        v = v + self.dt_over_tau * (-(v - self.v_rest) + conductance) * active
        spike = (v >= self.v_th).float() * active
        v = torch.where(spike > 0, torch.full_like(v, self.v_rest), v)
        refrac = torch.where(spike > 0, torch.zeros_like(refrac), 
                             torch.clamp(refrac + 0.1 / self.t_refrac, 0, 1))
        return v, spike, refrac


class SparseLIFModel(nn.Module):
    """Full brain model: Poisson → AlphaSynapse → LIF."""
    
    def __init__(self, n_neurons, dt=0.1, weights=None):
        super().__init__()
        self.n_neurons = n_neurons
        self.dt = dt
        self.poisson = PoissonSpikeGenerator(dt)
        self.synapse = AlphaSynapse(n_neurons, dt)
        self.neuron = LIFNeuron(n_neurons, dt)
        self.weights = weights
    
    def state_init(self, batch, device):
        conductance, delay_buffer = self.synapse.state_init(batch, device)
        v, refrac = self.neuron.state_init(batch, device)
        return conductance, delay_buffer, v, refrac
    
    def forward(self, rates, conductance, delay_buffer, v, refrac):
        input_spikes = self.poisson(rates)
        recurrent_input = torch.sparse.mm(self.weights, input_spikes.t()).t()
        conductance, delay_buffer = self.synapse(input_spikes, recurrent_input, conductance, delay_buffer, refrac)
        v, spike, refrac = self.neuron(conductance, v, refrac)
        return conductance, delay_buffer, v, refrac, spike


if __name__ == "__main__":
    engine = BrainEngine()
    engine.initialize()
    
    rates = engine.stimulate_neurons(list(range(500)), rate=200.0)
    
    for i in range(10):
        spikes = engine.step(rates, n_steps=10)
        print(f"Step {i}: {spikes[0].sum().item():.0f} spikes")
