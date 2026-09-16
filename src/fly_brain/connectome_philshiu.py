"""Wrapper around philshiu/Drosophila_brain_model — the real Drosophila connectome.

Uses Brian2 LIF simulation with FlyWire v783 connectivity (138K neurons, 15M synapses).
Not used for action selection (PPO does that) — runs in background for logging/visualization
of real connectome activity responding to game stimuli.
"""
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

# Brian2 imports (lazy — only loaded when simulate is called)
_brian2_loaded = False
_NeuronGroup = None
_Synapses = None
_PoissonInput = None
_SpikeMonitor = None
_Network = None
_mV = None
_ms = None
_Hz = None


def _lazy_load_brian2():
    global _brian2_loaded, _NeuronGroup, _Synapses, _PoissonInput, _SpikeMonitor, _Network, _mV, _ms, _Hz
    if _brian2_loaded:
        return
    from brian2 import NeuronGroup, Synapses, PoissonInput, SpikeMonitor, Network, mV, ms, Hz
    _NeuronGroup = NeuronGroup
    _Synapses = Synapses
    _PoissonInput = PoissonInput
    _SpikeMonitor = SpikeMonitor
    _Network = Network
    _mV = mV
    _ms = ms
    _Hz = Hz
    _brian2_loaded = True


class FlyConnectomeModel:
    """Real Drosophila connectome model based on philshiu's Brian2 implementation.
    
    FlyWire v783: ~138K neurons, ~15M synapses, full brain + optic lobes.
    """
    
    # Default model parameters (from philshiu paper)
    DEFAULT_PARAMS = {
        't_run': 1000 * 1,  # ms (will be replaced)
        'n_run': 1,         # number of trials
        'v_0': -52,         # mV — resting potential
        'v_rst': -52,       # mV — reset potential
        'v_th': -45,        # mV — spike threshold
        't_mbr': 20,        # ms — membrane time constant
        'tau': 5,           # ms — synaptic time constant
        't_rfc': 2.2,       # ms — refractory period
        't_dly': 1.8,       # ms — synaptic delay
        'w_syn': 0.275,     # mV — synaptic weight
        'r_poi': 150,       # Hz — default Poisson rate
        'r_poi2': 0,        # Hz — second Poisson rate
    }
    
    def __init__(self, data_dir: str = None):
        """
        data_dir: path to directory containing Completeness_783.csv and Connectivity_783.parquet
        """
        if data_dir is None:
            data_dir = "D:/fly-brain-philshiu"
        
        self.data_dir = Path(data_dir)
        self.path_comp = self.data_dir / "Completeness_783.csv"
        self.path_con = self.data_dir / "Connectivity_783.parquet"
        
        self.n_neurons = None
        self.synapse_count = None
        self._load_metadata()
    
    def _load_metadata(self):
        """Load metadata without building the full model."""
        df_comp = pd.read_csv(self.path_comp, index_col=0)
        self.n_neurons = len(df_comp)
        
        # Quick count of synapses from parquet (just read shape, not full file)
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(str(self.path_con))
        self.synapse_count = pf.metadata.num_rows
        
        print(f"[connectome] Loaded metadata: {self.n_neurons} neurons, {self.synapse_count} synapses")
    
    def stimulate_and_get_rates(self, neu_exc: List[int], rate_hz: float = 150.0,
                                 t_run_ms: int = 1000) -> Dict[int, float]:
        """
        Stimulate a set of neurons with Poisson input and return firing rates.
        
        This is the real Brian2 simulation — slow but accurate.
        Per philshiu benchmarks: ~20 min for 30 trials of 1000ms.
        
        Args:
            neu_exc: list of neuron indices to stimulate
            rate_hz: Poisson stimulation rate in Hz
            t_run_ms: simulation duration in ms
            
        Returns:
            dict mapping neuron_index -> firing_rate_hz
        """
        _lazy_load_brian2()
        
        # Load data
        df_comp = pd.read_csv(self.path_comp, index_col=0)
        df_con = pd.read_parquet(self.path_con)
        
        params = dict(self.DEFAULT_PARAMS)
        params['t_run'] = t_run_ms * _ms
        params['r_poi'] = rate_hz * _Hz
        
        # Brian2 equations
        eqs = '''
        dv/dt = (v_0 - v) / t_mbr : volt (unless refractory)
        dg/dt = -g / tau : volt
        rfc : second
        '''
        eq_th = 'v > v_th'
        eq_rst = 'v = v_rst'
        
        # Create neurons
        neu = _NeuronGroup(
            N=len(df_comp),
            model=eqs,
            method='linear',
            threshold=eq_th,
            reset=eq_rst,
            refractory='rfc',
            name='default_neurons',
            namespace=params,
        )
        neu.v = params['v_0'] * _mV
        neu.g = 0
        neu.rfc = params['t_rfc'] * _ms
        
        # Create synapses
        syn = _Synapses(neu, neu, 'w : volt', on_pre='g += w',
                        delay=params['t_dly'] * _ms, name='default_synapses')
        
        # Connect synapses
        i_pre = df_con['Presynaptic_Index'].values
        i_post = df_con['Postsynaptic_Index'].values
        syn.connect(i=i_pre, j=i_post)
        syn.w = params['w_syn'] * _mV
        
        # Poisson stimulation
        for idx in neu_exc:
            p = _PoissonInput(target=neu[idx], target_var='v', N=1,
                              rate=rate_hz * _Hz, weight=params['w_syn'] * _mV)
            neu[idx].rfc = 0 * _ms  # no refractory for Poisson targets
        
        # Spike monitor
        spk_mon = _SpikeMonitor(neu, name='spike_monitor')
        
        # Network and run
        net = _Network(neu, syn, spk_mon)
        net.run(t_run_ms * _ms, report='text')
        
        # Extract firing rates
        rates = {}
        spike_trains = spk_mon.spike_trains()
        for neuron_idx, times in spike_trains.items():
            rates[int(neuron_idx)] = len(times) / (t_run_ms / 1000.0)  # Hz
        
        return rates


# Global singleton
_model_instance = None

def get_fly_connectome():
    global _model_instance
    if _model_instance is None:
        _model_instance = FlyConnectomeModel()
    return _model_instance


if __name__ == "__main__":
    model = FlyConnectomeModel()
    print(f"[connectome] {model.n_neurons} neurons, {model.synapse_count} synapses")
