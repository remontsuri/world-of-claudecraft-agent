"""Build a bounded, measured MaleCNS v1.0 circuit for world-of-claudecraft.

Selection uses ANATOMY ONLY, never game outcomes (Fly Dino protocol, flyjump
scripts/build-connectome.py):

  1. Retain every descending neuron (superclass == descending_neuron).
  2. Retain their direct presynaptic partners (P1), ranked by total contact
     weight onto DNs, capped at --p1.
  3. Retain the second hop (P2), ranked by total contact weight onto P1,
     capped at --p2.
  4. Retain EVERY measured directed edge among the selected cells, including
     one-contact and recurrent edges. No edges are synthesized.

Input cells: for each of 13 named visual cell types, the 4 cells with the
largest total direct contact count onto descending neurons (Fly Dino ranking).
Output cells: the 64 DNs with the largest outgoing contact weight, plus a
forced set of named locomotion DNs (DNg13 L/R, DNp01 L/R = the user's mapped
readout; DNp09, MDN, DNa01/02, DNp20, DNpe017 from fly-craftax/doomfly).

Requires pyarrow. Memory-safe: the 485 MB edge table is read zero-copy via
memory map and filtered batch-by-batch.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/user/malecns")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "/home/user/fly-woc/data")
P1_CAP = 4000
P2_CAP = 8000
N_READOUT = 64
# Channel -> cell type assignment is an ENGINEERED mapping (Fly Dino: "an
# arbitrary, fixed engineering encoder ... no claimed biological interpretation").
# Types were required to have >=4 cells with direct DN contacts in the
# traced-only edge file; classic Fly Dino types LC9/LC11/LC15-LC22 lost their
# traced upstream there, so measured DN-projecting types replace them.
CHANNEL_TYPES = [("hp", "JO-FV"), ("resource", "GNG423"), ("in_combat", "BM_Vib"),
                 ("gcd_ready", "AN19A018"), ("target_exists", "LC4"), ("target_dist", "LPLC2"),
                 ("target_hp", "LPLC1"), ("target_sin", "LPLC4"), ("target_cos", "LT51"),
                 ("nearest_mob_dist", "LLPC1"), ("mob_pressure", "PVLP122"),
                 ("ability_ready", "LgLG3"), ("quest_progress", "BM_Taste")]
CHANNEL_NAMES = [c for c, _ in CHANNEL_TYPES]
FORCED_DN_TYPES = ["DNg13", "DNp01", "DNp09", "MDN", "DNa01", "DNa02", "DNp20", "DNpe017"]
# Sign convention: Shiu et al. / fly-craftax data.py; unknown falls back to the
# cell-type prediction, else 0 (no drive). A modeling assumption, not measured.
SIGN = {"acetylcholine": 1.0, "gaba": -1.0, "glutamate": -1.0, "histamine": -1.0,
        "dopamine": 1.0, "serotonin": 1.0, "octopamine": 1.0}


def sha256(path: Path) -> str:
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def load_annotations():
    ann = feather.read_table(DATA / "annotations.feather").to_pandas()
    ann = ann[ann.bodyId.notna()].copy()
    nt = feather.read_table(
        DATA / "neurotransmitters.feather", columns=["body", "consensus_nt", "celltype_predicted_nt"]
    ).to_pandas()
    df = ann.merge(nt, left_on="bodyId", right_on="body", how="left")
    sign = df.consensus_nt.map(SIGN)
    df["sign"] = sign.fillna(df.celltype_predicted_nt.map(SIGN)).fillna(0.0).astype(np.float32)
    df["side"] = df.somaSide.fillna(df.rootSide).fillna("unknown")
    df = df.sort_values("bodyId").reset_index(drop=True)
    return df


def edge_batches(path: Path):
    """Yield (pre, post, weight) numpy arrays batch-by-batch.

    The feather holds five columns; the two string type columns would blow the
    memory budget if the whole table were materialized, so each record batch
    is read and only the three numeric columns are converted.
    """
    with pa.memory_map(str(path)) as src:
        reader = pa.ipc.open_file(src)
        for i in range(reader.num_record_batches):
            batch = reader.get_record_batch(i)
            yield (batch.column("body_pre").to_numpy(zero_copy_only=False).astype(np.uint64),
                   batch.column("body_post").to_numpy(zero_copy_only=False).astype(np.uint64),
                   batch.column("weight").to_numpy(zero_copy_only=False).astype(np.int64))


def filter_edges(path: Path, post_set: np.ndarray | None, pre_post_set: tuple | None):
    """One streaming pass. Returns kept (pre, post, weight) arrays.

    post_set: keep edges whose post is in this set (hop pass).
    pre_post_set: (pre_set, post_set) keep edges inside both (final pass).
    """
    keep_pre, keep_post, keep_w = [], [], []
    for pre, post, w in edge_batches(path):
        if post_set is not None:
            m = np.isin(post, post_set, assume_unique=False)
        else:
            ps, qs = pre_post_set
            m = np.isin(pre, ps) & np.isin(post, qs)
        if m.any():
            keep_pre.append(pre[m]); keep_post.append(post[m]); keep_w.append(w[m])
    if not keep_pre:
        return np.zeros(0, np.uint64), np.zeros(0, np.uint64), np.zeros(0, np.int64)
    return np.concatenate(keep_pre), np.concatenate(keep_post), np.concatenate(keep_w)


def cap_by_weight(pre, post, w, targets: np.ndarray, cap: int):
    """Rank PREsynaptic cells projecting INTO targets by total contact weight."""
    m = np.isin(post, targets)
    cells = pre[m]
    uniq, inv = np.unique(cells, return_inverse=True)
    totals = np.bincount(inv, weights=w[m])
    order = np.lexsort((uniq, -totals))
    keep = uniq[order[:cap]] if cap and len(uniq) > cap else uniq
    return keep


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ann = load_annotations()
    body = ann.bodyId.to_numpy(np.uint64)
    dn_mask = (ann.superclass == "descending_neuron").to_numpy()
    dn_ids = np.sort(body[dn_mask])
    print(f"annotations: {len(ann)} cells, {len(dn_ids)} DNs")

    edges_path = DATA / "edges-traced.feather"
    src_hashes = {p.name: sha256(DATA / p.name) for p in
                  [Path("annotations.feather"), Path("neurotransmitters.feather"), Path("edges-traced.feather")]}
    print("source hashes computed")

    # Hop 1: direct presynaptic partners of DNs.
    pre1, post1, w1 = filter_edges(edges_path, dn_ids, None)
    print(f"hop1 edges onto DNs: {len(pre1)}")
    p1_ids = cap_by_weight(pre1, post1, w1, dn_ids, P1_CAP)

    # Hop 2: presynaptic partners of P1.
    pre2, post2, w2 = filter_edges(edges_path, p1_ids, None)
    print(f"hop2 edges onto P1: {len(pre2)}")
    p2_ids = cap_by_weight(pre2, post2, w2, p1_ids, P2_CAP)
    p2_ids = np.setdiff1d(p2_ids, np.union1d(dn_ids, p1_ids))

    V = np.union1d(np.union1d(dn_ids, p1_ids), p2_ids)
    print(f"core cells: {len(V)} (DN {len(dn_ids)} + P1 {len(p1_ids)} + P2 {len(p2_ids)})")

    # --- input cells: Fly Dino ranking per type onto DNs (from the hop-1 edge
    # pass); fallback tiers: P1, then the whole retained set. Selected BEFORE V
    # is finalized so every driven cell is inside the circuit. ---
    def rank_type(typ, tiers):
        ids = body[(ann.type == typ).to_numpy()]
        for tier, (e_pre, e_post, e_w) in enumerate(tiers):
            m = np.isin(e_pre, ids) & np.isin(e_post, np.union1d(dn_ids, p1_ids) if tier == 0 else V)
            if not m.any():
                continue
            cells = e_pre[m]
            uniq, inv = np.unique(cells, return_inverse=True)
            totals = np.bincount(inv, weights=e_w[m])
            order = np.lexsort((uniq, -totals))[:4]
            return uniq[order]
        return None

    input_bodies = []
    for ch, (chan, typ) in enumerate(CHANNEL_TYPES):
        chosen = rank_type(typ, [(pre1, post1, w1), (pre2, post2, w2)])
        if chosen is None:
            raise SystemExit(f"type {typ} has no contacts onto DNs or P1")
        input_bodies.append(chosen)
    input_set = np.unique(np.concatenate(input_bodies))
    V = np.union1d(V, input_set)
    idx = {int(b): i for i, b in enumerate(V)}
    inputs = []
    for ch, chosen in enumerate(input_bodies):
        for b in chosen:
            inputs.append([idx[int(b)], ch])
    print(f"input cells: {len(inputs)} across {len(CHANNEL_TYPES)} types; V now {len(V)}")

    # Final pass: every measured edge inside V (including the forced input cells).
    pre, post, w = filter_edges(edges_path, None, (V, V))
    print(f"internal edges retained: {len(pre)} ({w.sum()} contacts)")
    pre_i = np.array([idx[int(b)] for b in pre], np.int32)
    post_i = np.array([idx[int(b)] for b in post], np.int32)

    # --- readout DNs: top-N outgoing + forced named DNs ---
    m_out = np.isin(pre, dn_ids)
    cells = pre[m_out]
    uniq, inv = np.unique(cells, return_inverse=True)
    totals = np.bincount(inv, weights=w[m_out])
    order = np.lexsort((uniq, -totals))
    readout_bodies = set(int(b) for b in uniq[order[:N_READOUT]])
    forced = ann[(ann.type.isin(FORCED_DN_TYPES)) & dn_mask]
    forced_ids = set(int(b) for b in forced.bodyId)
    missing = forced_ids - set(int(b) for b in V)
    if missing:
        print(f"WARNING: forced DNs not in circuit (no traced upstream path kept): {sorted(missing)}")
    readout_bodies |= (forced_ids & set(int(b) for b in V))
    readout = sorted(idx[b] for b in readout_bodies)
    print(f"readout DNs: {len(readout)} (forced present: {len(forced_ids & set(int(b) for b in V))})")

    role = {}
    for b in dn_ids:
        role[int(b)] = "descending"
    for c, _ in inputs:
        role[int(V[c])] = "input"
    # ann is sorted by bodyId: vectorized metadata lookup for every selected cell
    pos = np.searchsorted(body, V)
    types = ann.type.to_numpy(); sides = ann.side.to_numpy()
    nts = ann.consensus_nt.to_numpy(); signs = ann.sign.to_numpy()
    nodes = []
    for k, b in enumerate(V):
        p = pos[k]
        nodes.append({"id": int(b), "i": int(idx[int(b)]),
                      "type": (None if types[p] != types[p] else str(types[p])),
                      "side": str(sides[p]),
                      "nt": (None if nts[p] != nts[p] else str(nts[p])),
                      "sign": float(signs[p]), "role": role.get(int(b), "interneuron")})
    edges = sorted([int(a), int(b), int(c)] for a, b, c in zip(pre_i, post_i, w))

    graph = {"version": "malecns-woc-circuit-v1", "nodes": nodes, "edges": edges,
             "inputs": inputs, "outputs": readout, "channels": CHANNEL_NAMES,
             "input_types": [t for _, t in CHANNEL_TYPES]}
    (OUT / "circuit.json").write_text(json.dumps(graph, separators=(",", ":")) + "\n")

    manifest = {
        "dataset": "FlyEM MaleCNS v1.0, min confidence 0.5, traced-only edges",
        "license": "CC BY 4.0",
        "source": "https://male-cns.janelia.org/download/",
        "sources": src_hashes,
        "nodes": len(V), "edges": len(edges), "synapticContacts": int(w.sum()),
        "descendingTotal": int(len(dn_ids)),
        "inputCells": len(inputs), "readoutCells": len(readout),
        "graphSha256": sha256(OUT / "circuit.json"),
        "selection": ("all descending neurons; top P1 presynaptic partners by contact weight onto DNs "
                      f"(cap {P1_CAP}); top P2 second-hop by contact weight onto P1 (cap {P2_CAP}); "
                      "all measured internal directed edges retained; ties by bodyId. No game outcomes used."),
        "assumptions": ("Engineered 13-channel obs-to-cell-type mapping; signed leaky-tanh rate dynamics; "
                        "ACh +1, GABA/Glu/histamine -1, DA/5HT/OA +1 (Shiu convention), unknown/predicted "
                        "fallback else 0. Not a physiological or whole-brain model."),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: manifest[k] for k in ("nodes", "edges", "synapticContacts", "inputCells", "readoutCells")}))
    print("circuit written to", OUT / "circuit.json")


if __name__ == "__main__":
    main()
