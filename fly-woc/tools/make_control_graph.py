#!/usr/bin/env python3
"""make_control_graph.py — контроли топологии для MaleCNS-схемы (свой, без чужого кода).

Зачем: утверждение «важна именно топология коннектома» проверяемо ТОЛЬКО против
схемы с той же плотностью и теми же степенями, но перепутанными связями.
Иначе результат не отличим от «любая сеть такой плотности».

    python3 tools/make_control_graph.py --mode degree --seed 1 --out data/circuit_rewired.json
    python3 tools/make_control_graph.py --mode er     --seed 1 --out data/circuit_er.json

Что сохраняется В ТОЧНОСТИ (поэтому контроль «matched»):
  * число узлов, их id/type/side/nt/sign/role — без изменений;
  * входы/выходы и раскладка каналов (`inputs`, `outputs`, `channels`, `input_types`);
  * входящая и исходящая степень КАЖДОГО узла (degree) либо только N и M (er);
  * мультимножество весов-контактов (перетасовывается, не пересэмплируется);
  * знак ребра по-прежнему берётся от пресинаптического нейрона (в схеме вес —
    это счётчик контактов, а знак живёт в узле; см. fly_brain.py: W[j,i] = c*s[j]/…).
Меняется ровно одно: кто с кем соединён.

Формат файла — тот же, что у data/circuit.json (version/nodes/edges/inputs/…),
плюс блок "control" с параметрами и результатами проверок.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def graph_stats(edges: np.ndarray, n_nodes: int) -> dict:
    pre, post = edges[:, 0].astype(np.int64), edges[:, 1].astype(np.int64)
    out = np.bincount(pre, minlength=n_nodes)
    inn = np.bincount(post, minlength=n_nodes)
    return {
        "n_nodes": int(n_nodes),
        "n_edges": int(edges.shape[0]),
        "out_degree_sum": int(out.sum()),
        "in_degree_sum": int(inn.sum()),
        "out_degree_sorted_hash": hashlib.sha256(np.sort(out).astype(np.int64).tobytes()).hexdigest()[:16],
        "in_degree_sorted_hash": hashlib.sha256(np.sort(inn).astype(np.int64).tobytes()).hexdigest()[:16],
        "self_loops": int(np.sum(pre == post)),
        "weight_sum": int(edges[:, 2].sum()),
    }


def _encode(pre: np.ndarray, post: np.ndarray, n_nodes: int) -> np.ndarray:
    return pre.astype(np.int64) * n_nodes + post.astype(np.int64)


def rewire_degree(pre: np.ndarray, post: np.ndarray, n_nodes: int,
                  rng: np.random.Generator, n_swaps: int,
                  max_attempt_factor: float = 20.0) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Обмен рёбер (double edge swap): степени сохраняются в точности, граф остаётся простым.

    Почему не «тасовка полудуг»: у хабов связей больше, чем возможных целей, и простой
    граф с такой последовательностью степеней не существует — конфигурационная модель
    вырождается в мультиграф. Обмен рёбер такого не допускает: меняются только цели,
    дубликаты и петли не создаются, out-степень каждого нейрона не трогается вовсе, а
    вес остаётся на своём ребре — то есть профиль исходящих весов нейрона сохраняется.
    """
    pre, post = pre.copy(), post.copy()
    seen = set(_encode(pre, post, n_nodes).tolist())
    m = pre.shape[0]
    applied = attempts = 0
    budget = int(n_swaps * max_attempt_factor) + 1000
    while applied < n_swaps and attempts < budget:
        batch = min(200_000, max(1000, (n_swaps - applied) * 2))
        idx = rng.integers(0, m, size=(batch, 2))
        attempts += batch
        for a, b in idx.tolist():
            if a == b:
                continue
            p1, q1 = int(pre[a]), int(post[a])
            p2, q2 = int(pre[b]), int(post[b])
            if p1 == q1 or p2 == q2:          # петли в исходнике не трогаем
                continue
            if p1 == q2 or p2 == q1:          # новые петли запрещены
                continue
            n1, n2 = p1 * n_nodes + q2, p2 * n_nodes + q1
            if n1 in seen or n2 in seen:      # дубликаты запрещены
                continue
            c1, c2 = p1 * n_nodes + q1, p2 * n_nodes + q2
            seen.discard(c1); seen.discard(c2)
            seen.add(n1); seen.add(n2)
            post[a], post[b] = q2, q1
            applied += 1
            if applied >= n_swaps:
                break
    return pre, post, applied, attempts


def rewire_er(pre: np.ndarray, post: np.ndarray, n_nodes: int,
              rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, int]:
    """Эрдёш–Реньи с тем же N и M: пары случайны, петли исключены."""
    m = pre.shape[0]
    out: list[np.ndarray] = []
    got = 0
    rejects = 0
    while got < m:
        batch = max(int((m - got) * 1.15), 1024)
        a = rng.integers(0, n_nodes, size=batch, dtype=np.int64)
        b = rng.integers(0, n_nodes, size=batch, dtype=np.int64)
        ok = a != b
        code = _encode(a[ok], b[ok], n_nodes)
        _, first = np.unique(code, return_index=True)
        keep = np.zeros(code.size, dtype=bool)
        keep[first] = True
        a, b = a[ok][keep], b[ok][keep]
        rejects += int(batch - a.size)
        out.append(np.stack([a, b], axis=1))
        got += a.size
    pairs = np.concatenate(out, axis=0)[:m]
    return pairs[:, 0], pairs[:, 1], rejects


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", type=Path, default=Path(__file__).parent.parent / "data" / "circuit.json")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mode", choices=["degree", "er"], default="degree")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--swaps", type=float, default=1.0,
                    help="сколько обменов рёбер сделать в режиме degree, в долях от M (1.0 = M)")
    ap.add_argument("--subgraph-n", type=int, default=0,
                    help="взять индуцированный подграф на N узлах (для быстрых тестов)")
    args = ap.parse_args()

    raw = args.src.read_bytes()
    src_sha = hashlib.sha256(raw).hexdigest()
    graph = json.loads(raw)
    nodes, edges = graph["nodes"], graph["edges"]
    n_nodes = len(nodes)
    arr = np.asarray(edges, dtype=np.int64)

    if args.subgraph_n:
        rng0 = np.random.default_rng(args.seed ^ 0x5EED)
        keep_nodes = np.sort(rng0.choice(n_nodes, size=min(args.subgraph_n, n_nodes), replace=False))
        remap = {int(v): i for i, v in enumerate(keep_nodes)}
        mask = np.isin(arr[:, 0], keep_nodes) & np.isin(arr[:, 1], keep_nodes)
        sub = arr[mask]
        new_pre = np.fromiter((remap[int(v)] for v in sub[:, 0]), dtype=np.int64, count=sub.shape[0])
        new_post = np.fromiter((remap[int(v)] for v in sub[:, 1]), dtype=np.int64, count=sub.shape[0])
        arr = np.stack([new_pre, new_post, sub[:, 2]], axis=1)
        nodes = [nodes[int(v)] for v in keep_nodes]
        # входы/выходы подграфа: сохраняем только те, что остались
        idx_map = {int(old["i"]): i for i, old in enumerate(nodes)}
        for i, nd in enumerate(nodes):
            nd["i"] = i
        graph["nodes"] = nodes
        graph["inputs"] = [[idx_map[a], b] for a, b in graph["inputs"] if a in idx_map]
        graph["outputs"] = [idx_map[v] for v in graph["outputs"] if v in idx_map]
        n_nodes = len(nodes)

    pre, post = arr[:, 0].copy(), arr[:, 1].copy()
    weights = arr[:, 2].copy()
    rng = np.random.default_rng(args.seed)

    applied = attempts = rejected = 0
    if args.mode == "degree":
        new_pre, new_post, applied, attempts = rewire_degree(
            pre, post, n_nodes, rng, n_swaps=int(args.swaps * pre.shape[0]))
        new_w = weights.copy()                # вес остаётся на своём ребре: профиль нейрона цел
    else:
        new_pre, new_post, rejected = rewire_er(pre, post, n_nodes, rng)
        new_w = weights.copy()
        rng.shuffle(new_w)                    # веса: тот же мультимножество, разложен заново

    new_edges = np.stack([new_pre, new_post, new_w], axis=1)
    before = graph_stats(arr, n_nodes)
    after = graph_stats(new_edges, n_nodes)

    checks = {
        "n_nodes_equal": before["n_nodes"] == after["n_nodes"],
        "n_edges_equal": before["n_edges"] == after["n_edges"],
        "weight_multiset_equal": bool(np.array_equal(np.sort(weights), np.sort(new_w))),
        "out_degree_preserved": before["out_degree_sorted_hash"] == after["out_degree_sorted_hash"],
        "in_degree_preserved": before["in_degree_sorted_hash"] == after["in_degree_sorted_hash"],
        "self_loops_before": before["self_loops"],
        "self_loops_after": after["self_loops"],
        "pairs_changed_share": float(np.mean(_encode(pre, post, n_nodes) != _encode(new_pre, new_post, n_nodes))),
    }

    out = dict(graph)
    out["version"] = "malecns-woc-circuit-control-v1"
    out["edges"] = [[int(a), int(b), int(w)] for a, b, w in new_edges]
    out["control"] = {
        "mode": args.mode, "seed": args.seed, "swaps_applied": int(applied),
        "swap_attempts": int(attempts), "rejected_stubs": int(rejected),
        "source_file": args.src.name, "source_sha256": src_sha,
        "subgraph_n": args.subgraph_n or None,
        "matches_source": {
            "n_nodes": True, "n_edges": True, "weight_multiset": True,
            "degree_sequences": bool(args.mode == "degree"),
            "node_properties": True, "inputs_outputs": True,
        },
        "checks": checks,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))

    ok = (checks["n_nodes_equal"] and checks["n_edges_equal"] and checks["weight_multiset_equal"]
          and (args.mode != "degree" or (checks["out_degree_preserved"] and checks["in_degree_preserved"])))
    print(f"режим={args.mode} seed={args.seed} узлов={after['n_nodes']} рёбер={after['n_edges']} "
          f"изменено пар={checks['pairs_changed_share']:.1%} петли {before['self_loops']}->{after['self_loops']}")
    print(f"степени сохранены: out={checks['out_degree_preserved']} in={checks['in_degree_preserved']} | "
          f"веса сохранены: {checks['weight_multiset_equal']}")
    print(f"записано: {args.out} ({args.out.stat().st_size/1e6:.1f} МБ) sha={hashlib.sha256(args.out.read_bytes()).hexdigest()[:16]}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
