#!/usr/bin/env python3
"""Element-wise comparison of the traced-only circuit and the full-table circuit.

Memory-frugal: int64 numpy arrays only (no Python dicts/sets of 1.87M edges).
"""
from __future__ import annotations

import json
import numpy as np


def load(path: str):
    """Edges are stored as NODE INDICES; map them back to bodyIds before comparing.

    (Comparing indices directly is wrong: the two builds differ by one cell, which
    shifts every later index and makes ~48% of pairs look different.)
    """
    g = json.load(open(path))
    nodes = {n["id"]: n for n in g["nodes"]}
    idx2body = np.array([n["id"] for n in g["nodes"]], dtype=np.int64)
    e = np.array(g["edges"], dtype=np.int64)
    e = np.column_stack([idx2body[e[:, 0]], idx2body[e[:, 1]], e[:, 2]])
    assert e[:, :2].max() < 2**31, "bodyId exceeds 31 bits"
    key = e[:, 0] * 2**31 + e[:, 1]          # collision-free composite key
    order = np.argsort(key, kind="stable")
    return nodes, key[order], e[order]


def main() -> None:
    nt, kt, et = load("/home/user/data/circuit-traced-v3/circuit.json")
    nf, kf, ef = load("/home/user/data/circuit-full/circuit.json")

    print(f"traced : {len(nt):>6} nodes  {len(et):>9,} edges  {int(et[:,2].sum()):>12,} contacts")
    print(f"full   : {len(nf):>6} nodes  {len(ef):>9,} edges  {int(ef[:,2].sum()):>12,} contacts")

    st, sf = set(nt), set(nf)
    print(f"\nnode ids identical: {st == sf}")
    for label, ids, src in (("only in traced", sorted(st - sf), nt), ("only in full", sorted(sf - st), nf)):
        for i in ids:
            n = src[i]
            print(f"  {label}: bodyId {i}  type={n['type']}  nt={n['nt']}  role={n['role']}  sign={n['sign']}")

    common, it, if_ = np.intersect1d(kt, kf, return_indices=True)
    only_t = np.setdiff1d(kt, kf, assume_unique=False)
    only_f = np.setdiff1d(kf, kt, assume_unique=False)
    print(f"\nedge pairs: common {len(common):,} | traced-only {len(only_t):,} | full-only {len(only_f):,}")
    print(f"  {100*len(common)/len(kt):.3f}% of traced pairs exist in the full table")
    wt, wf = et[it, 2], ef[if_, 2]
    same = int((wt == wf).sum())
    print(f"  common pairs with identical contact weight: {same:,} "
          f"({100*same/len(common):.3f}%); differing: {len(common)-same:,}")
    if len(common) - same:
        d = np.nonzero(wt != wf)[0]
        print(f"    examples (pre,post,traced_w,full_w):")
        for j in d[:5]:
            pre, post = divmod(int(common[j]), 2**31)
            print(f"      {pre},{post}  {int(wt[j])} vs {int(wf[j])}")
    if len(only_t):
        m = np.isin(kt, only_t, assume_unique=False)
        print(f"  traced-only edges: contacts {int(et[m,2].sum()):,}")
    if len(only_f):
        m = np.isin(kf, only_f, assume_unique=False)
        print(f"  full-only edges:   contacts {int(ef[m,2].sum()):,}")


if __name__ == "__main__":
    main()
