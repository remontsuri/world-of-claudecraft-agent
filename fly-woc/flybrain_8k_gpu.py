#!/usr/bin/env python3
"""FlyBrain8KGPU — оптимизированный 8K MaleCNS subset на GPU (CSR format)."""
import json
import time
from pathlib import Path

import numpy as np
import torch

from device_utils import resolve_device
from scipy.sparse import csr_matrix


class FlyBrain8KGPU:
    """Frozen MaleCNS 8K subset with rate-based propagation on GPU."""

    def __init__(self, circuit_path=None, device=None, n_iters=5):
        self.device = resolve_device(device)   # единый выбор: аргумент -> WOC_DEVICE -> cuda/mps -> cpu
        self.n_iters = n_iters
        if circuit_path is None:
            circuit_path = str(Path(__file__).resolve().parent / 'data' / 'circuit.json')
        print(f'[FlyBrain8KGPU] loading from {circuit_path}... device={self.device}')

        with open(circuit_path) as f:
            graph = json.load(f)

        self.graph_path = Path(circuit_path)
        n = len(graph['nodes'])
        self.n = n

        # Build sparse weight matrix
        pre = np.array([e[0] for e in graph['edges']], dtype=np.int32)
        post = np.array([e[1] for e in graph['edges']], dtype=np.int32)
        contacts = np.array([e[2] for e in graph['edges']], dtype=np.float64)
        signs = np.array([nd['sign'] for nd in graph['nodes']], dtype=np.float64)

        # Fly Dino normalization
        denom = np.zeros(n)
        np.add.at(denom, post, contacts * np.abs(signs[pre]))
        w = np.where(denom[post] > 0, contacts * signs[pre] / np.maximum(denom[post], 1e-12), 0.0)

        # Build scipy CSR first, then convert to torch CSR (much faster than COO)
        W_scipy = csr_matrix((w.astype(np.float32), (post, pre)), shape=(n, n))

        # Convert to torch CSR tensor on GPU
        indptr = torch.tensor(W_scipy.indptr, dtype=torch.int32, device=self.device)
        indices = torch.tensor(W_scipy.indices, dtype=torch.int32, device=self.device)
        data = torch.tensor(W_scipy.data, dtype=torch.float32, device=self.device)
        self.W_csr = torch.sparse_csr_tensor(indptr, indices, data, size=(n, n))

        # Input/output indices
        self.input_idx = torch.tensor([c for c, _ in graph['inputs']], dtype=torch.long, device=self.device)
        self.input_ch = torch.tensor([ch for _, ch in graph['inputs']], dtype=torch.long, device=self.device)
        self.out_idx = torch.tensor(graph['outputs'], dtype=torch.long, device=self.device)
        self.n_dn = len(graph['outputs'])
        # см. fly_brain.py: 1.87M рёбер в Python-объектах (~0.5 ГБ) держать не нужно
        self.graph = {"n_nodes": n, "n_edges": len(pre), "channels": graph.get("channels")}
        del graph

        # Pre-compute input mapping for vectorized drive
        self.input_map = []
        for ch in range(13):
            mask = (self.input_ch == ch)
            if mask.any():
                self.input_map.append((ch, self.input_idx[mask]))
            else:
                self.input_map.append((ch, None))

        print(f'[FlyBrain8KGPU] {n} neurons, {self.n_dn} DN, {len(graph["edges"])} edges, iters={n_iters}, device={self.device}')

        # State
        self.h = None
        self.reset(1)

    def reset(self, batch_size=1):
        self.h = torch.zeros(batch_size, self.n, device=self.device)

    def step(self, features, silenced=False):
        batch_size = features.shape[0]
        if self.h is None or self.h.shape[0] != batch_size:
            self.reset(batch_size)

        if silenced:
            self.h.zero_()
            return torch.zeros(batch_size, self.n_dn, device=self.device)

        leak = 0.3
        gain = 1.4

        for _ in range(self.n_iters):
            # Drive input neurons using pre-computed mapping
            u = torch.zeros(batch_size, self.n, device=self.device)
            for ch, idx in self.input_map:
                if idx is not None:
                    u[:, idx] = features[:, ch].unsqueeze(1).expand_as(u[:, idx])

            # CSR matmul: W @ h^T
            inp = 2.0 * u + gain * torch.sparse.mm(self.W_csr, self.h.t()).t()
            self.h = leak * self.h + (1 - leak) * torch.tanh(inp)

        out = 4.0 * self.h[:, self.out_idx]
        return out


if __name__ == '__main__':
    for n_iters in [3, 5, 10]:
        brain = FlyBrain8KGPU(n_iters=n_iters)
        features = torch.randn(2, 13, device=brain.device)

        for _ in range(5):
            out = brain.step(features)

        brain.reset(2)
        start = time.time()
        for _ in range(100):
            out = brain.step(features)
        torch.cuda.synchronize()
        elapsed = time.time() - start
        print(f'iters={n_iters}: 100 steps in {elapsed:.3f}s ({elapsed/100*1000:.1f} ms/step), out range [{out.min().item():.3f}, {out.max().item():.3f}]')
