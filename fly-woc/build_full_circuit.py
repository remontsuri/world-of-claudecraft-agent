#!/usr/bin/env python3
"""build_full_circuit.py — собрать нормализованный circuit.json для полного MaleCNS 211K."""
import json
import time
from pathlib import Path

import numpy as np
import pyarrow.feather as ft
import torch
from scipy.sparse import coo_matrix, csr_matrix


DATA_DIR = Path('D:/world-of-claudecraft/data/male_cns')
OUT_JSON = Path('D:/world-of-claudecraft-agent/fly-woc/data/circuit_full.json')


def main():
    t0 = time.time()
    print(f'[build] reading annotations...')
    ann = ft.read_table(f'{DATA_DIR}/body-annotations.feather').to_pandas()
    n = len(ann)
    body2idx = dict(zip(ann['bodyId'], range(n)))
    print(f'[build] {n} neurons')

    print(f'[build] reading neurotransmitters...')
    nt = ft.read_table(f'{DATA_DIR}/body-neurotransmitters.feather').to_pandas()
    # Columns: 'body', 'consensus_nt' — use consensus neurotransmitter
    nt_map = dict(zip(nt['body'], nt['consensus_nt']))
    sign_map = {'ach': 1, 'gaba': -1, 'glu': -1, 'da': 1, '5ht': 1, 'oa': 1}
    body_sign = {int(b): sign_map.get(t, 0) for b, t in zip(nt['body'], nt['consensus_nt'])}

    print(f'[build] reading cached sparse weights...')
    # nosemgrep: torch_unsafe_load — MaleCNS v1.0 is a published scientific dataset
    cache = torch.load(f'{DATA_DIR}/male_cns_sparse.pt', weights_only=True)
    indices = cache['W_indices'].numpy()
    values = cache['W_values'].numpy()
    print(f'[build] {indices.shape[1]} edges')

    # Build normalized weights: W[j,i] = sign[i] * c[j,i] / sum_abs_c[j,i]
    # Fly Dino normalization: incoming signed weights normalized by total absolute signed contact count
    print(f'[build] normalizing weights...')
    rows, cols = indices[0], indices[1]  # post, pre

    # Compute per-postsynaptic normalization factor
    abs_vals = np.abs(values)
    denom = np.zeros(n, dtype=np.float64)
    np.add.at(denom, rows, abs_vals)

    # Avoid division by zero
    mask = denom[rows] > 0
    norm_vals = np.where(mask, values * np.sign(values), 0.0)  # sign already in values? No, values are raw
    # Actually: W[j,i] = c[j,i] * sign[pre_i] / sum_abs_c[j]
    pre_signs = np.array([body_sign.get(int(c), 0) for c in cols], dtype=np.float64)
    signed_vals = values * pre_signs
    norm_vals = np.where(mask, signed_vals / denom[rows], 0.0)

    # Build scipy CSR
    print(f'[build] building CSR matrix...')
    W_csr = csr_matrix((norm_vals.astype(np.float32), (rows, cols)), shape=(n, n))
    print(f'[build] CSR: {W_csr.shape}, nnz: {W_csr.nnz}')

    # Select DN readout neurons (top-64 outgoing + forced 18)
    print(f'[build] selecting DN readout...')
    out_degree = np.array(W_csr.getnnz(axis=1)).flatten()
    top_dn = np.argsort(out_degree)[-64:]

    # Force-add known DN body IDs (from current circuit)
    forced_ids = [11074, 512006, 10001, 10010, 10009, 10013, 10002, 10020, 10008, 10005, 10006]
    forced_idx = [body2idx[b] for b in forced_ids if b in body2idx]
    all_dn = np.unique(np.concatenate([top_dn, forced_idx]))
    print(f'[build] {len(all_dn)} DN readout neurons')

    # Select input neurons (top-13 channels x 4 cells = 52)
    # For simplicity, use top in-degree neurons as inputs
    in_degree = np.array(W_csr.getnnz(axis=0)).flatten()
    top_in = np.argsort(in_degree)[-52:]
    print(f'[build] {len(top_in)} input neurons')

    # Build circuit.json
    # Nodes: all 211K (too large for JSON, store as indices)
    # Instead, store sparse representation
    circuit = {
        'n': int(n),
        'W_data': {
            'indices': W_csr.indices.tolist(),
            'indptr': W_csr.indptr.tolist(),
            'data': W_csr.data.tolist(),
            'shape': list(W_csr.shape),
        },
        'inputs': top_in.tolist(),
        'outputs': all_dn.tolist(),
        'input_channels': 13,
        'n_dn': int(len(all_dn)),
        'source': 'MaleCNS v1.0, 211577 neurons, normalized',
    }

    print(f'[build] writing {OUT_JSON}...')
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump(circuit, f)
    print(f'[build] done in {time.time()-t0:.1f}s')


if __name__ == '__main__':
    main()
