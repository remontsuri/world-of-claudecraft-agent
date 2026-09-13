"""connectome.py — load FlyWire v783 connectivity matrix and build CSR weights."""
import numpy as np
import pandas as pd
import torch
from pathlib import Path

DATA_DIR = Path("D:/fly-brain/data")
PARQUET_PATH = DATA_DIR / "2025_Connectivity_783.parquet"
COMPLETENESS_PATH = DATA_DIR / "2025_Completeness_783.csv"


def load_connectome(parquet_path=PARQUET_PATH, completeness_path=COMPLETENESS_PATH):
    """Load connectivity table and build flywire_id -> contiguous index mapping.
    
    Returns:
        df: connectivity DataFrame
        flyid2i: dict mapping flywire_id -> contiguous index
        i2flyid: ndarray mapping contiguous index -> flywire_id
        n_neurons: total number of unique neurons
    """
    df = pd.read_parquet(parquet_path)
    
    # Build unified index from both pre and post neurons
    all_ids = pd.concat([df["Presynaptic_ID"], df["Postsynaptic_ID"]]).unique()
    all_ids.sort()
    
    flyid2i = {fid: i for i, fid in enumerate(all_ids)}
    i2flyid = np.array(all_ids, dtype=np.int64)
    n_neurons = len(all_ids)
    
    print(f"[connectome] {n_neurons} neurons, {len(df)} directed edges")
    print(f"[connectome] weight range: {df['Connectivity'].min()}-{df['Connectivity'].max()}")
    
    return df, flyid2i, i2flyid, n_neurons


def build_sparse_weights(df, flyid2i, n_neurons, w_scale=0.275, device="cpu"):
    """Build sparse CSR weight matrix W[i,j] = w_scale * connectivity.
    
    W[i,j] represents synaptic weight from neuron j to neuron i (column-stochastic).
    """
    pre_idx = df["Presynaptic_ID"].map(flyid2i).values.astype(np.int64)
    post_idx = df["Postsynaptic_ID"].map(flyid2i).values.astype(np.int64)
    weights = df["Connectivity"].values.astype(np.float32) * w_scale
    
    # Build sparse tensor: W[post, pre] = weight
    indices = torch.tensor(np.stack([post_idx, pre_idx]), dtype=torch.long)
    values = torch.tensor(weights, dtype=torch.float32)
    
    W = torch.sparse_coo_tensor(indices, values, (n_neurons, n_neurons))
    W = W.coalesce().to(device)
    
    print(f"[connectome] sparse weight matrix: {W.shape}, {W._nnz()} nonzeros, device={device}")
    return W


def load_completeness(completeness_path=COMPLETENESS_PATH):
    """Load neuron completeness table (proofread status)."""
    comp = pd.read_csv(completeness_path)
    id_col = comp.columns[0]
    completed = set(comp[comp["Completed"] == True][id_col].values)
    print(f"[connectome] {len(completed)} proofread neurons")
    return completed


if __name__ == "__main__":
    df, flyid2i, i2flyid, n = load_connectome()
    W = build_sparse_weights(df, flyid2i, n)
    completed = load_completeness()
