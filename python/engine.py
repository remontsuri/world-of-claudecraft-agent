"""engine.py — LIF spiking neural network with WTA lateral inhibition and DA-STDP plasticity.

Per document spec:
- Leaky Integrate-and-Fire (LIF) neuron dynamics
- Winner-Take-All for motor action selection
- Dopamine-modulated STDP (PPL101 / PAM clusters) for KC → MBON plasticity

GPU-accelerated via PyTorch. Falls back to CPU if CUDA unavailable.
"""
import numpy as np
import torch
import torch.nn as nn
from scipy import sparse
import pandas as pd
import os
import pickle


class LIFNeuronGroup:
    """A group of LIF neurons with shared parameters."""
    
    def __init__(self, n_neurons, tau_m=20.0, v_rest=-65.0, v_thresh=-50.0, 
                 v_reset=-70.0, refractory_period=2, device='cpu'):
        """
        Args:
            n_neurons: number of neurons
            tau_m: membrane time constant (ms)
            v_rest: resting potential (mV)
            v_thresh: threshold potential (mV)
            v_reset: reset potential (mV)
            refractory_period: refractory period in time steps
        """
        self.n = n_neurons
        self.tau_m = tau_m
        self.v_rest = v_rest
        self.v_thresh = v_thresh
        self.v_reset = v_reset
        self.refractory_period = refractory_period
        self.device = device
        
        # State
        self.v = torch.full((n_neurons,), v_rest, device=device)
        self.refractory = torch.zeros(n_neurons, dtype=torch.long, device=device)
        self.spiked = torch.zeros(n_neurons, dtype=torch.bool, device=device)
    
    def reset(self):
        self.v[:] = self.v_rest
        self.refractory[:] = 0
        self.spiked[:] = False
    
    def step(self, I_synaptic, I_ext=0.0, dt=1.0):
        """
        One LIF integration step.
        
        Args:
            I_synaptic: [n] total synaptic current from presynaptic partners
            I_ext: [n] external sensory current
            dt: time step (ms)
        
        Returns:
            spikes: [n] boolean spike tensor
        """
        # Update refractory
        active = self.refractory == 0
        self.refractory = torch.clamp(self.refractory - 1, min=0)
        
        # Leaky integration
        dv = (-(self.v - self.v_rest) + I_synaptic + I_ext) / self.tau_m * dt
        self.v = torch.where(active, self.v + dv, self.v)
        
        # Spike
        self.spiked = self.v >= self.v_thresh
        
        # Reset
        self.v = torch.where(self.spiked, torch.tensor(self.v_reset, device=self.device), self.v)
        self.refractory = torch.where(self.spiked, torch.tensor(self.refractory_period, device=self.device), self.refractory)
        
        return self.spiked


class WTAMotorDecoder:
    """Winner-Take-All lateral inhibition for motor action selection.
    
    Groups compete via lateral inhibition — only the highest-firing group
    survives, preventing conflicting motor commands.
    """
    
    def __init__(self, group_names, inhibition_strength=0.5, threshold=0.1):
        """
        Args:
            group_names: list of motor group names
            inhibition_strength: how strongly groups suppress each other
            threshold: minimum firing rate to be considered active
        """
        self.group_names = group_names
        self.inhibition_strength = inhibition_strength
        self.threshold = threshold
        self.n_groups = len(group_names)
        self.name_to_idx = {name: i for i, name in enumerate(group_names)}
        
        # State
        self.group_activity = torch.zeros(self.n_groups)
        self.winner = None
    
    def register_neurons(self, neuron_groups):
        """
        Map neuron indices to motor groups.
        
        Args:
            neuron_groups: dict {name: list_of_neuron_indices}
        """
        self.neuron_groups = neuron_groups
        self.group_indices = {}
        for name, indices in neuron_groups.items():
            self.group_indices[name] = torch.tensor(indices, dtype=torch.long)
    
    def compute_group_activity(self, firing_rates):
        """
        Compute mean firing rate per group, then apply WTA.
        
        Args:
            firing_rates: [n_neurons] firing rate tensor
        
        Returns:
            winner_name: name of winning group (or None)
            group_activities: [n_groups] activity before inhibition
        """
        activities = torch.zeros(self.n_groups)
        
        for i, name in enumerate(self.group_names):
            idx = self.group_indices[name]
            if len(idx) > 0:
                activities[i] = firing_rates[idx].mean()
        
        self.group_activity = activities
        
        # Lateral inhibition: subtract max * inhibition_strength from others
        if activities.max() > self.threshold:
            winner_idx = activities.argmax()
            winner_val = activities[winner_idx]
            
            # Suppress all others
            suppression = winner_val * self.inhibition_strength
            activities = torch.where(
                torch.arange(self.n_groups) == winner_idx,
                activities,
                activities - suppression
            )
            activities = torch.clamp(activities, min=0)
            
            # Re-check winner
            if activities[winner_idx] > 0:
                self.winner = self.group_names[winner_idx]
            else:
                self.winner = None
        else:
            self.winner = None
        
        return self.winner, activities
    
    def decode_action(self):
        """Convert winner to discrete action index."""
        if self.winner is None:
            return -1  # NOOP
        return self.name_to_idx[self.winner]


class DA_STDP:
    """Dopamine-modulated Spike-Timing-Dependent Plasticity.
    
    Implements the rule from the document:
    Δw = η * DA * f(t_pre - t_post)
    
    where f is the STDP window (asymmetric exponential).
    Applied to KC → MBON synapses in Mushroom Body.
    """
    
    def __init__(self, n_pre, n_post, learning_rate=0.001, tau_plus=20.0, tau_minus=20.0,
                 A_plus=0.01, A_minus=0.01, device='cpu'):
        """
        Args:
            n_pre: number of presynaptic neurons (KCs)
            n_post: number of postsynaptic neurons (MBONs)
            learning_rate: η
            tau_plus: time constant for LTP (ms)
            tau_minus: time constant for LTD (ms)
            A_plus: amplitude for LTP
            A_minus: amplitude for LTD
        """
        self.n_pre = n_pre
        self.n_post = n_post
        self.lr = learning_rate
        self.tau_plus = tau_plus
        self.tau_minus = tau_minus
        self.A_plus = A_plus
        self.A_minus = A_minus
        self.device = device
        
        # Synaptic weights (sparse)
        self.W = torch.zeros(n_pre, n_post, device=device)
        
        # Spike history (for STDP)
        self.pre_spike_times = torch.full((n_pre,), -1000.0, device=device)
        self.post_spike_times = torch.full((n_post,), -1000.0, device=device)
    
    def reset(self):
        self.pre_spike_times[:] = -1000.0
        self.post_spike_times[:] = -1000.0
    
    def update(self, pre_spikes, post_spikes, dopamine, t):
        """
        Apply DA-STDP update.
        
        Args:
            pre_spikes: [n_pre] boolean — which KCs spiked
            post_spikes: [n_post] boolean — which MBONs spiked
            dopamine: scalar — DA concentration (from PPL101/PAM)
            t: current time step
        """
        # Update spike times
        self.pre_spike_times[pre_spikes] = t
        self.post_spike_times[post_spikes] = t
        
        # STDP window
        # For each pre-post pair:
        # If pre fires before post: LTP (if DA > 0)
        # If post fires before pre: LTD (if DA > 0) or no change
        
        dt = self.post_spike_times.unsqueeze(0) - self.pre_spike_times.unsqueeze(1)  # [pre, post]
        
        # LTP window (pre before post, dt > 0)
        ltp = self.A_plus * torch.exp(-dt / self.tau_plus) * (dt > 0).float()
        
        # LTD window (post before pre, dt < 0)  
        ltd = -self.A_minus * torch.exp(dt / self.tau_minus) * (dt < 0).float()
        
        # Combined
        dw = (ltp + ltd) * self.lr * dopamine
        
        # Apply only where spikes occurred
        pre_mask = pre_spikes.float().unsqueeze(1)
        post_mask = post_spikes.float().unsqueeze(0)
        
        self.W += dw * pre_mask * post_mask
        
        # Hard bounds
        self.W = torch.clamp(self.W, 0, 10)


class FlyBrainEngine:
    """Full connectome simulation engine.
    
    Loads MaleCNS or Hemibrain, runs LIF neurons, WTA motor selection, 
    and DA-STDP plasticity.
    """
    
    def __init__(self, hemibrain_path=None, device='cpu'):
        """
        Args:
            hemibrain_path: path to hemibrain CSV dir (or None for default)
            device: 'cpu' or 'cuda'
        """
        self.device = device
        
        if hemibrain_path is None:
            hemibrain_path = 'data/connectome/exported-traced-adjacencies-v1.2'
        
        self.hemibrain_path = hemibrain_path
        
        # Load connectome
        print('Loading connectome...')
        self.neurons = pd.read_csv(os.path.join(hemibrain_path, 'traced-neurons.csv'))
        conns = pd.read_csv(os.path.join(hemibrain_path, 'traced-total-connections.csv'))
        
        self.n_neurons = len(self.neurons)
        self.id2idx = dict(zip(self.neurons['bodyId'], range(self.n_neurons)))
        
        # Build sparse W
        W_cache = os.path.join(hemibrain_path, 'W_sparse.pt')
        if os.path.exists(W_cache):
            print('Loading cached W...')
            self.W_scipy = pickle.load(open(W_cache, 'rb'))
        else:
            print('Building sparse W...')
            rows, cols, weights = [], [], []
            for _, row in conns.iterrows():
                pre = self.id2idx.get(row['bodyId_pre'])
                post = self.id2idx.get(row['bodyId_post'])
                if pre is not None and post is not None:
                    rows.append(pre)
                    cols.append(post)
                    weights.append(row['weight'])
            
            W = sparse.csr_matrix(
                (weights, (rows, cols)),
                shape=(self.n_neurons, self.n_neurons)
            )
            W_max = W.max()
            self.W_scipy = (W / W_max).tocsr()
            pickle.dump(self.W_scipy, open(W_cache, 'wb'))
            print(f'Cached W to {W_cache}')
        
        # Pre-build torch W_t for matmul
        W_t_scipy = self.W_scipy.tocoo()
        W_t_indices = torch.tensor(np.array([W_t_scipy.row, W_t_scipy.col]), dtype=torch.long, device=device)
        W_t_values = torch.tensor(W_t_scipy.data, dtype=torch.float32, device=device)
        self.W_t = torch.sparse_coo_tensor(W_t_indices, W_t_values, size=W_t_scipy.shape).coalesce()
        
        # LIF neuron group
        print(f'Creating LIF neurons ({self.n_neurons})...')
        self.neurons_group = LIFNeuronGroup(
            self.n_neurons,
            tau_m=20.0,
            v_rest=-65.0,
            v_thresh=-50.0,
            v_reset=-70.0,
            refractory_period=2,
            device=device
        )
        
        # Sensory/Motor classification (simplified for hemibrain)
        # In full MaleCNS, these would be anatomically defined
        self.sensory_mask = self._classify_sensory()
        self.motor_mask = self._classify_motor()
        self.inter_mask = ~(self.sensory_mask | self.motor_mask)
        
        # Motor groups (WTA)
        # For hemibrain, we create 4 virtual motor groups (no real VNC)
        self.motor_groups = {
            'move_forward': torch.where(self.motor_mask)[0][:500],
            'turn': torch.where(self.motor_mask)[0][500:1000],
            'attack': torch.where(self.motor_mask)[0][1000:1500],
            'interact': torch.where(self.motor_mask)[0][1500:2000],
        }
        
        self.wta = WTAMotorDecoder(
            list(self.motor_groups.keys()),
            inhibition_strength=0.5,
            threshold=0.05
        )
        self.wta.register_neurons(self.motor_groups)
        
        # DA-STDP for KC→MBON (placeholder — need actual MB neuron IDs)
        # In real MaleCNS, KCs are in MB(R) ROI, MBONs are MBON.* types
        n_kc = int(self.sensory_mask.sum())  # placeholder
        n_mbon = 100  # placeholder
        self.stdp = DA_STDP(n_kc, n_mbon, device=device)
        
        # Dopamine level (from PPL101)
        self.dopamine = 0.0
        
        print(f'Engine ready: {self.n_neurons} neurons')
        print(f'  Sensory: {int(self.sensory_mask.sum())}')
        print(f'  Motor: {int(self.motor_mask.sum())}')
        print(f'  Inter: {int(self.inter_mask.sum())}')
    
    def _classify_sensory(self):
        """Classify sensory neurons by ROI (simplified)."""
        # Use neuron types that start with visual projection prefixes
        types = self.neurons['type'].fillna('')
        sensory = types.str.startswith('LC') | types.str.startswith('VPN') | types.str.startswith('vPN')
        return torch.tensor(sensory.values)
    
    def _classify_motor(self):
        """Classify motor neurons (hemibrain has no real VNC — use projection types)."""
        # In MaleCNS, would use VNC.* types
        types = self.neurons['type'].fillna('')
        motor = types.str.startswith('DN') | types.str.startswith('GF')
        # If too few, pad with random for now
        if motor.sum() < 2000:
            n_needed = 2000 - motor.sum()
            non_sensory = ~(types.str.startswith('LC') | types.str.startswith('VPN'))
            candidates = non_sensory[non_sensory].index
            extra = candidates[:n_needed]
            motor.iloc[extra] = True
        return torch.tensor(motor.values)
    
    def reset(self):
        self.neurons_group.reset()
        self.stdp.reset()
        self.dopamine = 0.0
    
    def step(self, sensory_input, dt=1.0):
        """
        One simulation step.
        
        Args:
            sensory_input: [n_sensory] external current to sensory neurons
            dt: time step (ms)
        
        Returns:
            winner: winning motor group name
            action: discrete action index
            spikes: [n_neurons] spike tensor
        """
        # Sensory current vector
        I_ext = torch.zeros(self.n_neurons, device=self.device)
        sensory_indices = torch.where(self.sensory_mask)[0]
        if len(sensory_input) > 0 and len(sensory_indices) > 0:
            n_min = min(len(sensory_input), len(sensory_indices))
            I_ext[sensory_indices[:n_min]] = sensory_input[:n_min]
        
        # Synaptic current: W @ spikes
        prev_spikes = self.neurons_group.spiked.float().to(self.device)
        I_syn = torch.sparse.mm(self.W_t, prev_spikes.unsqueeze(1)).squeeze()
        
        # LIF step
        spikes = self.neurons_group.step(I_syn, I_ext, dt)
        
        # WTA motor selection
        firing_rates = self.neurons_group.v - self.neurons_group.v_rest
        firing_rates = torch.clamp(firing_rates / 20, 0, 1)  # normalize
        winner, activities = self.wta.compute_group_activity(firing_rates)
        action = self.wta.decode_action()
        
        # DA-STDP update (simplified — would use actual KC/MBON indices)
        # For now, just decay dopamine
        self.dopamine *= 0.95
        
        return winner, action, spikes
    
    def set_dopamine(self, da):
        """Set dopamine concentration (from PPL101/PAM)."""
        self.dopamine = da
    
    def get_action(self, obs_vector):
        """
        High-level interface: obs -> action.
        
        Args:
            obs_vector: numpy or tensor [obs_dim]
        
        Returns:
            action: discrete action index
        """
        if not isinstance(obs_vector, torch.Tensor):
            obs_vector = torch.tensor(obs_vector, dtype=torch.float32)
        
        # Encode as sensory current (rate coding)
        # Map obs_dim features to sensory neuron firing rates
        obs_dim = len(obs_vector)
        sensory_rates = torch.zeros(self.n_neurons, device=self.device)
        sensory_indices = torch.where(self.sensory_mask)[0]
        
        # Simple mapping: repeat obs to fill sensory neurons
        n_sensory = len(sensory_indices)
        if n_sensory > 0:
            repeated = obs_vector.repeat(n_sensory // obs_dim + 1)[:n_sensory]
            sensory_indices = sensory_indices[:len(repeated)]
            # Scale to current (0-10 mV)
            sensory_rates[sensory_indices] = repeated * 10
        
        # Run one step
        winner, action, spikes = self.step(sensory_rates)
        
        return action


if __name__ == '__main__':
    # Test
    engine = FlyBrainEngine()
    engine.reset()
    
    # Random observation
    obs = np.random.randn(16)
    
    import time
    times = []
    for i in range(100):
        t0 = time.time()
        action = engine.get_action(obs)
        times.append(time.time() - t0)
    
    print(f'get_action: {np.mean(times)*1000:.2f}ms ± {np.std(times)*1000:.2f}ms')
    print(f'Action: {action}')
    print(f'Winner: {engine.wta.winner}')
    print(f'Dopamine: {engine.dopamine:.3f}')
