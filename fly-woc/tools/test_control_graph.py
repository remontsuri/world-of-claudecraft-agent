#!/usr/bin/env python3
"""test_control_graph.py — приёмка контролей топологии без игры, GPU и сети.

Сравниваем контроль не с полной схемой, а с её же подграфом-источником
(`--swaps 0` даёт ровно ту выборку узлов, с которой потом работаем): иначе тест
ругался бы на законное уменьшение схемы.

Проверяем:
  1) degree: in/out-степени каждого узла совпадают точно, петли не размножаются,
     пары уникальны, вес остаётся на своём ребре (профиль нейрона цел);
  2) er: те же N и M, пары уникальны, петли исключены, мультимножество весов то же;
  3) узлы и их свойства, inputs/outputs/channels/input_types не изменились;
  4) детерминизм по seed и «swaps=0 = исходник»;
  5) обмен рёбер реально произошёл.

Запуск:
    python3 tools/test_control_graph.py           # синтетика + подграф реальной схемы
    python3 tools/test_control_graph.py --full    # плюс полная схема (8835 узлов)
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
SCRIPT = HERE / "tools" / "make_control_graph.py"
REAL = HERE / "data" / "circuit.json"
NODE_KEYS = ("id", "type", "side", "nt", "sign", "role")


def make_fixture(path: Path, n: int = 60, m: int = 300, seed: int = 3) -> None:
    rng = np.random.default_rng(seed)
    nodes = [{"id": 10000 + i, "i": i, "type": f"T{i % 5}", "side": "L" if i % 2 else "R",
              "nt": "acetylcholine" if i % 3 else "gaba", "sign": 1.0 if i % 3 else -1.0,
              "role": "descending" if i < 5 else "interneuron"} for i in range(n)]
    pairs = set()
    while len(pairs) < m:
        a, b = int(rng.integers(0, n)), int(rng.integers(0, n))
        if a != b:
            pairs.add((a, b))
    # исходник бывает с петлями: контроль не должен их размножать
    edges = [[a, b, int(rng.integers(1, 50))] for a, b in sorted(pairs)] + [[7, 7, 5], [19, 19, 3]]
    path.write_text(json.dumps({
        "version": "malecns-woc-circuit-v1", "nodes": nodes, "edges": edges,
        "inputs": [[0, 0], [1, 1], [2, 0]], "outputs": [0, 1, 2],
        "channels": [f"ch{i}" for i in range(3)], "input_types": ["a", "b", "c"]},
        separators=(",", ":")))


def run(src: Path, out: Path, mode: str = "degree", seed: int = 1, swaps: float = 1.0,
        sub: int = 0) -> dict:
    cmd = [sys.executable, str(SCRIPT), "--in", str(src), "--out", str(out),
           "--mode", mode, "--seed", str(seed), "--swaps", str(swaps)]
    if sub:
        cmd += ["--subgraph-n", str(sub)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    tail = res.stdout.strip().splitlines()[-1] if res.stdout else ""
    return {"rc": res.returncode, "out": tail, "err": res.stderr[-400:]}


def check(base_path: Path, out_path: Path, mode: str, label: str) -> list[str]:
    base, out = json.loads(base_path.read_text()), json.loads(out_path.read_text())
    be, oe = np.asarray(base["edges"], dtype=np.int64), np.asarray(out["edges"], dtype=np.int64)
    issues: list[str] = []

    if len(base["nodes"]) != len(out["nodes"]):
        issues.append(f"число узлов {len(base['nodes'])} -> {len(out['nodes'])}")
    else:
        for a, b in zip(base["nodes"], out["nodes"]):
            if {k: a[k] for k in NODE_KEYS} != {k: b[k] for k in NODE_KEYS}:
                issues.append(f"свойства узла {a['id']} изменились"); break
        if [nd["i"] for nd in out["nodes"]] != list(range(len(out["nodes"]))):
            issues.append("индексы узлов не подряд")
    for key in ("inputs", "outputs", "channels", "input_types"):
        if base.get(key) != out.get(key):
            issues.append(f"{key} изменились")

    if be.shape != oe.shape:
        issues.append(f"число рёбер {be.shape[0]} -> {oe.shape[0]}")
    else:
        n = len(out["nodes"])
        bo, bi = np.bincount(be[:, 0], minlength=n), np.bincount(be[:, 1], minlength=n)
        oo, oi = np.bincount(oe[:, 0], minlength=n), np.bincount(oe[:, 1], minlength=n)
        if mode == "degree":
            if not (np.array_equal(bo, oo) and np.array_equal(bi, oi)):
                issues.append("степени не сохранены точно")
            if not np.array_equal(be[:, 0], oe[:, 0]) or not np.array_equal(np.sort(be[:, 2]), np.sort(oe[:, 2])):
                issues.append("веса/пре-нейроны сдвинулись (профиль нейрона обязан сохраняться)")
        elif not np.array_equal(np.sort(be[:, 2]), np.sort(oe[:, 2])):
            issues.append("мультимножество весов не совпало")
        lb, la = int(np.sum(be[:, 0] == be[:, 1])), int(np.sum(oe[:, 0] == oe[:, 1]))
        if la > lb:
            issues.append(f"петель стало больше: {lb} -> {la}")
        pairs = oe[:, 0] * n + oe[:, 1]
        if np.unique(pairs).size != pairs.size:
            issues.append("появились дубликаты пар")

    ctl = out.get("control", {})
    checks = ctl.get("checks", {})
    for key in ("n_nodes_equal", "n_edges_equal", "weight_multiset_equal"):
        if not checks.get(key):
            issues.append(f"self-check {key} = false")
    if mode == "degree" and not (checks.get("out_degree_preserved") and checks.get("in_degree_preserved")):
        issues.append("self-check степеней не пройден")
    if not ctl.get("source_sha256"):
        issues.append("нет ссылки на sha источника")
    share = checks.get("pairs_changed_share", 0.0)
    if mode == "degree" and share < 0.2:
        issues.append(f"граф почти не изменился: {share:.1%}")
    if mode == "er" and share < 0.99:
        issues.append(f"er обязан менять все пары, а изменил {share:.1%}")

    print(f"  {'OK  ' if not issues else 'FAIL'} {label}: пар изменено {share:.1%}, "
          f"петель {checks.get('self_loops_before')}->{checks.get('self_loops_after')}, "
          f"рёбер {oe.shape[0]}")
    for i in issues:
        print(f"        - {i}")
    return issues


def main(argv: list[str]) -> int:
    full = "--full" in argv
    ok = True
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        print("1) синтетическая схема (с исходными петлями)")
        fixture = tmp / "small.json"
        make_fixture(fixture)
        for mode in ("degree", "er"):
            out = tmp / f"small_{mode}.json"
            r = run(fixture, out, mode=mode)
            if r["rc"] != 0:
                print(f"  FAIL {mode}: генератор упал: {r['err']}"); ok = False; continue
            ok &= not check(fixture, out, mode, f"small/{mode}")

        print("2) детерминизм и swaps=0")
        a, b, c, z = (tmp / f"{n}.json" for n in ("a", "b", "c", "z"))
        run(fixture, a, seed=11); run(fixture, b, seed=11); run(fixture, c, seed=12)
        run(fixture, z, swaps=0.0)
        same = hashlib.sha256(a.read_bytes()).hexdigest() == hashlib.sha256(b.read_bytes()).hexdigest()
        diff = hashlib.sha256(a.read_bytes()).hexdigest() != hashlib.sha256(c.read_bytes()).hexdigest()
        identical = np.array_equal(np.asarray(json.loads(fixture.read_text())["edges"]),
                                   np.asarray(json.loads(z.read_text())["edges"]))
        ok &= bool(same and diff and identical)
        print(f"  {'OK  ' if same and diff else 'FAIL'} один seed -> тот же файл: {same}; другой seed -> другой: {diff}")
        print(f"  {'OK  ' if identical else 'FAIL'} swaps=0 -> граф равен исходному: {identical}")

        if REAL.exists():
            print("3) подграф реальной схемы (400 узлов)")
            base = tmp / "real_base.json"
            r = run(REAL, base, swaps=0.0, seed=5, sub=400)
            if r["rc"] != 0:
                print(f"  FAIL подграф не собрался: {r['err']}"); ok = False
            else:
                for mode in ("degree", "er"):
                    out = tmp / f"real_{mode}.json"
                    r = run(REAL, out, mode=mode, sub=400, seed=5)
                    if r["rc"] != 0:
                        print(f"  FAIL real/{mode}: {r['err']}"); ok = False; continue
                    ok &= not check(base, out, mode, f"real/{mode}")

            if full:
                print("4) ПОЛНАЯ схема: 8835 узлов, 1.87M рёбер")
                for mode in ("degree", "er"):
                    out = tmp / f"full_{mode}.json"
                    r = run(REAL, out, mode=mode, swaps=0.25, seed=21)
                    if r["rc"] != 0:
                        print(f"  FAIL full/{mode}: {r['err']}"); ok = False; continue
                    ok &= not check(REAL, out, mode, f"full/{mode}")
                    print(f"        {r['out']}")
        else:
            print("3) скип: нет data/circuit.json")

    print("\nитог:", "контроли корректны" if ok else "есть провалы")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
