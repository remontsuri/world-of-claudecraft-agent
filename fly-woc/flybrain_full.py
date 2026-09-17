#!/usr/bin/env python3
"""FlyBrainFull — полный MaleCNS 211K нейронов на GPU с rate-based propagation."""
import json
import time
from pathlib import Path

import numpy as np
import torch

from device_utils import resolve_device


class FlyBrainFull:
    """Frozen MaleCNS 211K full graph with rate-based propagation on GPU."""

    def __init__(self, circuit_path=None, device=None):
        if circuit_path is None:
            circuit_path = str(Path(__file__).parent / 'data' / 'circuit_full.json')
        self.device = resolve_device(device)   # единый выбор: аргумент -> WOC_DEVICE -> cuda/mps -> cpu
        print(f'[FlyBrainFull] loading from {circuit_path}...')

        with open(circuit_path) as f:
            ckpt = json.load(f)

        self.n = ckpt['n']
        self.n_dn = ckpt['n_dn']

        # Build sparse tensor on GPU
        w = ckpt['W_data']
        indptr = torch.tensor(w['indptr'], dtype=torch.int32)
        indices = torch.tensor(w['indices'], dtype=torch.int32)
        data = torch.tensor(w['data'], dtype=torch.float32)
        shape = tuple(w['shape'])
        W_csr = torch.sparse_csr_tensor(indptr, indices, data, size=shape).to(self.device)
        self.W_gpu = W_csr

        # Input/output indices
        self.input_idx = torch.tensor(ckpt['inputs'], dtype=torch.long, device=self.device)
        self.output_idx = torch.tensor(ckpt['outputs'], dtype=torch.long, device=self.device)

        # Map input channels (13) to first 13 input neurons
        self.input_channel_idx = self.input_idx[:13]

        print(f'[FlyBrainFull] {self.n} neurons, {self.n_dn} DN, {self.W_gpu._nnz()} edges, device={self.device}')

        # State
        self.h = None
        self.reset(1)

    def reset(self, batch_size=1):
        self.h = torch.zeros(batch_size, self.n, device=self.device)

    def step(self, features, silenced=False):
        """
        features: (batch, 13) engineered features
        Returns: (batch, n_dn) DN activities
        """
        batch_size = features.shape[0]
        if self.h is None or self.h.shape[0] != batch_size:
            self.reset(batch_size)

        if silenced:
            self.h.zero_()
            return torch.zeros(batch_size, self.n_dn, device=self.device)

        # Drive input neurons: u = 2 * (features - 0.5)
        drive = 2.0 * (features - 0.5)  # (batch, 13)

        # Add drive to input neurons
        u = self.h.clone()
        u[:, :13] = u[:, :13] + drive

        # Rate-based propagation: h ← 0.3·h + 0.7·tanh(u + 1.4·W·h)
        leak = 0.3
        gain = 1.4
        for _ in range(3):
            inp = u + gain * torch.sparse.mm(self.W_gpu, self.h.t()).t()
            self.h = (1 - leak) * self.h + leak * torch.tanh(inp)

        # Output = 4 * h[DN]
        out = 4.0 * self.h[:, self.output_idx[:self.n_dn]]
        return out


if __name__ == '__main__':
    import time

    brain = FlyBrainFull()
    features = torch.randn(2, 13, device=brain.device)

    # Warmup
    for _ in range(5):
        out = brain.step(features)
    print(f'Output shape: {out.shape}, range: [{out.min().item():.3f}, {out.max().item():.3f}]')

    # Benchmark
    brain.reset(2)
    start = time.time()
    for _ in range(100):
        out = brain.step(features)
    elapsed = time.time() - start
    print(f'100 steps: {elapsed:.3f}s ({elapsed/100*1000:.1f} ms/step)')
    print(f'Output: {out[0, :5]}')
