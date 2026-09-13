"""Connectome-based SNN policy for fly RL.

Uses hemibrain sparse weight matrix W as backbone architecture.
Inputs: WoC observations → encoded as neural activity
Outputs: Motor neuron activity → WoC actions
Training: BC init → PPO fine-tune
"""
import numpy as np
import torch
import torch.nn as nn
from scipy import sparse
import pandas as pd
import os


class ConnectomePolicy(nn.Module):
    def __init__(self, obs_dim=64, hidden_dim=512, action_dim=4, hemibrain_path=None):
        super().__init__()
        
        if hemibrain_path is None:
            hemibrain_path = 'data/connectome/exported-traced-adjacencies-v1.2'
        
        self.hemibrain_path = hemibrain_path
        
        # Load hemibrain data
        print('Loading hemibrain data...')
        self.neurons = pd.read_csv(os.path.join(hemibrain_path, 'traced-neurons.csv'))
        conns = pd.read_csv(os.path.join(hemibrain_path, 'traced-total-connections.csv'))
        
        self.id2idx = dict(zip(self.neurons['bodyId'], range(len(self.neurons))))
        self.n_neurons = len(self.neurons)
        
        # Cache W for fast subsequent loads
        W_cache = os.path.join(hemibrain_path, 'W_cached.pt')
        if os.path.exists(W_cache):
            print('Loading cached W...')
            W_data = torch.load(W_cache, weights_only=True)
            self.W = torch.sparse_coo_tensor(
                W_data['W_indices'], W_data['W_values'], size=tuple(W_data['W_size'])
            ).coalesce()
        else:
            # Build sparse weight matrix
            print('Building sparse W...')
            rows = []
            cols = []
            weights = []
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
            
            # Normalize W (synaptic weights → [0,1] range)
            W_max = W.max()
            W_norm = W / W_max
            
            # Convert to torch sparse COO
            rows_nz, cols_nz = W_norm.nonzero()
            indices = torch.tensor(np.array([rows_nz, cols_nz]), dtype=torch.long)
            values = torch.tensor(W_norm.data, dtype=torch.float32)
            self.W = torch.sparse_coo_tensor(indices, values, size=W_norm.shape).coalesce()
            
            # Cache W for subsequent loads
            torch.save({
                'W_indices': self.W.indices(),
                'W_values': self.W.values(),
                'W_size': list(self.W.shape),
            }, W_cache)
            print(f'Cached W to {W_cache}')
        
        # Sensory/Motor ROI classification (hemibrain)
        self.sensory_rois = ['AL(L)', 'AL(R)', 'AME(R)', 'LO(R)', 'LOP(R)', 'ME(R)', 'gL(L)', 'gL(R)']
        self.motor_rois = []  # hemibrain has no VNC
        
        # Trainable components
        self.obs_encoder = nn.Sequential(
            nn.Linear(obs_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, self.n_neurons),
            nn.Sigmoid()  # firing rate [0,1]
        )
        
        self.motor_decoder = nn.Sequential(
            nn.Linear(self.n_neurons, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, action_dim)
        )
        
        # Recurrent state
        self.h = None
        
        # PPO head
        self.value_head = nn.Linear(self.n_neurons, 1)
        
        print(f'ConnectomePolicy: {self.n_neurons} neurons, {self.W._nnz()} synapses')
        print(f'  Sensory ROIs: {self.sensory_rois}')
        print(f'  Obs dim: {obs_dim}, Action dim: {action_dim}')
    
    def reset_state(self, batch_size=1, device='cpu'):
        self.h = torch.zeros(batch_size, self.n_neurons, device=device)
    
    def forward(self, obs, h_prev=None):
        """
        obs: [batch, obs_dim]
        returns: action_logits, value, h_new
        """
        if h_prev is None:
            if self.h is None:
                self.reset_state(batch_size=obs.shape[0], device=obs.device)
            h_prev = self.h
        
        # Encode observation as sensory input
        sensory_input = self.obs_encoder(obs)  # [batch, n_neurons]
        
        # SNN update: H_new = ReLU(W @ H_prev + sensory_input)
        batch_size = obs.shape[0]
        h_flat = h_prev.view(batch_size, self.n_neurons)
        
        # Linear aggregation: W @ H_t (sparse matmul)
        W_h = torch.sparse.mm(self.W.t(), h_flat.t()).t()  # [batch, n_neurons]
        
        # Update with sensory input + decay (tanh for stability)
        h_new = torch.tanh(W_h * 0.01 + sensory_input)  # scale W_h to prevent explosion
        h_new = h_new * 0.9 + h_prev * 0.1
        
        # Safety clamp
        h_new = torch.clamp(h_new, -5, 5)
        
        # Motor decoding
        action_logits = self.motor_decoder(h_new)
        
        # Value
        value = self.value_head(h_new)
        
        # Store state
        self.h = h_new.detach()
        
        return action_logits, value, h_new
    
    @torch.no_grad()
    def get_action(self, obs, deterministic=False):
        """
        obs: tensor [obs_dim] or [batch, obs_dim]
        returns: action, log_prob, value, h_new
        """
        if obs.dim() == 1:
            obs = obs.unsqueeze(0)
        
        logits, value, h = self.forward(obs)
            
        if deterministic:
            action = logits.argmax(dim=-1)
        else:
            probs = torch.softmax(logits, dim=-1)
            action = torch.multinomial(probs, 1).squeeze(-1)
            
        log_prob = torch.log_softmax(logits, dim=-1).gather(1, action.unsqueeze(1)).squeeze(1)
            
        return action, log_prob, value, h
    
    def get_config(self):
        return {
            'n_neurons': self.n_neurons,
            'n_synapses': self.W._nnz(),
            'obs_dim': self.obs_encoder[0].in_features,
            'action_dim': self.motor_decoder[-1].out_features,
            'sensory_rois': self.sensory_rois,
            'motor_rois': self.motor_rois,
        }
    
    def freeze_connectome(self):
        """Freeze W backbone for BC training"""
        # W is already frozen (buffer), just ensure grad is off
        pass
    
    def unfreeze_connectome(self):
        """Unfreeze W for fine-tuning (PPO)"""
        # Convert W to Parameter for training
        W_dense = self.W.to_dense()
        self.W_param = nn.Parameter(W_dense)
        del self.W
        self.W = self.W_param


class WoCObservationEncoder:
    """Encode WoC game state into obs vector for ConnectomePolicy"""
    
    def __init__(self):
        self.feature_names = [
            'player_x', 'player_y', 'player_z',
            'player_hp', 'player_max_hp',
            'nearest_mob_dist', 'nearest_mob_type',
            'nearest_item_dist', 'nearest_item_type',
            'time_of_day', 'game_tick',
            'has_quest', 'quest_type',
            'inventory_count', 'copper',
        ]
        self.dim = len(self.feature_names)
    
    def encode(self, game_state):
        """Convert WoC game state dict to tensor [dim]"""
        features = [
            game_state.get('player_x', 0) / 1000,
            game_state.get('player_y', 0) / 1000,
            game_state.get('player_z', 0) / 1000,
            game_state.get('player_hp', 100) / 100,
            game_state.get('player_max_hp', 100) / 100,
            min(game_state.get('nearest_mob_dist', 100), 100) / 100,
            hash(game_state.get('nearest_mob_type', '')) % 100 / 100,
            min(game_state.get('nearest_item_dist', 100), 100) / 100,
            hash(game_state.get('nearest_item_type', '')) % 100 / 100,
            game_state.get('time_of_day', 0) / 24,
            (game_state.get('game_tick', 0) % 1000) / 1000,
            1.0 if game_state.get('has_quest', False) else 0.0,
            hash(game_state.get('quest_type', '')) % 10 / 10,
            min(game_state.get('inventory_count', 0), 64) / 64,
            min(game_state.get('copper', 0), 10000) / 10000,
        ]
        return torch.tensor(features, dtype=torch.float32)
    
    def action_to_step(self, action_idx):
        """Convert action index to WoC step command"""
        actions = [
            {'type': 'move', 'direction': 'forward'},
            {'type': 'move', 'direction': 'backward'},
            {'type': 'move', 'direction': 'left'},
            {'type': 'move', 'direction': 'right'},
        ]
        return actions[action_idx]


if __name__ == '__main__':
    # Test
    policy = ConnectomePolicy(obs_dim=16, action_dim=4)
    policy.reset_state(batch_size=2)
    
    obs = torch.randn(2, 16)
    logits, value, h = policy.forward(obs)
    
    print(f'Output shapes: logits={logits.shape}, value={value.shape}, h={h.shape}')
    print(f'Config: {policy.get_config()}')
    
    # Test action sampling
    action, log_prob, val, h_new = policy.get_action(obs)
    print(f'Action: {action}, log_prob: {log_prob}, value: {val}')
