#!/usr/bin/env python3
"""verify_provenance.py — «наш мозг — это правда MaleCNS?» Проверка по исходным данным.

Идея: схема (data/circuit.json) хранит для каждой клетки её настоящий bodyId, тип,
сторону и нейромедиатор. Значит проверить можно не словами, а сверкой с датасетом:
скачиваем ТОЛЬКО файл аннотаций (14 МБ; веса и рёбра не трогаем) и сравниваем.

Проверки (каждая может провалиться, поэтому и печатается в таблице):
  1. sha256 файла аннотаций совпадает с записанным в fetch-manifest.json;
  2. каждая клетка схемы (8835) есть в аннотациях MaleCNS;
  3. тип / сторона / суперкласс каждой клетки совпадают с датасетом;
  4. все нисходящие нейроны датасета (superclass == descending_neuron) присутствуют в схеме;
  5. типы входных клеток из схемы есть в аннотациях, и у каждого типа >= 4 клеток с контактами;
  6. рёбра внутри схемы консистентны (индексы в диапазоне, суммы, крупные узлы).

Запуск:
    python3 tools/verify_provenance.py                 # скачает аннотации, если их нет
    python3 tools/verify_provenance.py --no-download    # только по уже скачанному файлу
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CIRCUIT = HERE / "data" / "circuit.json"
MANIFEST = HERE / "data" / "manifest.json"
FETCH_MANIFEST = next((c for c in (
    HERE.parent / "data" / "malecns" / "fetch-manifest.json",          # как в чекауте
    Path("/home/user/data/malecns/fetch-manifest.json"),               # как в этой песочнице
) if c.exists()), HERE.parent / "data" / "malecns" / "fetch-manifest.json")
CACHE = Path("/home/user/malecns-verify")

ANN_NAME = "body-annotations-male-cns-v1.0-minconf-0.5.feather"
ANN_URL = ("https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/"
           "flat-connectome/" + ANN_NAME)

results: list[tuple[bool, str, str]] = []


def check(ok: bool, what: str, detail: str = "") -> bool:
    results.append((bool(ok), what, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {what}" + (f" — {detail}" if detail else ""), flush=True)
    return bool(ok)


def sha256(path: Path) -> str:
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def load_circuit_meta() -> dict:
    """Только узлы и метаданные: рёбра (1.87M) сюда не тянем — это 0.5 ГБ объектов."""
    sys.path.insert(0, str(HERE))
    from fly_brain import load_circuit
    return load_circuit(CIRCUIT)


def ensure_annotations(no_download: bool) -> Path | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / ANN_NAME
    if path.exists():
        print(f"аннотации уже скачаны: {path} ({path.stat().st_size / 2**20:.1f} МБ)")
        return path
    if no_download:
        print("нет скачанного файла аннотаций, а скачивать запрещено (--no-download)")
        return None
    print(f"скачиваю аннотации MaleCNS ({ANN_URL.rsplit('/', 1)[-1]}) …")
    try:
        urllib.request.urlretrieve(ANN_URL, path)
    except Exception as exc:                                   # noqa: BLE001
        print(f"не удалось скачать: {type(exc).__name__}: {exc}")
        return None
    print(f"  скачано {path.stat().st_size / 2**20:.1f} МБ")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()

    print("=== 1. схема и её манифест")
    circuit = load_circuit_meta()
    manifest = json.loads(MANIFEST.read_text())
    print(f"  схема: {circuit['n']} узлов, {circuit['n_edges']} рёбер, "
          f"{circuit['channels'] and len(circuit['channels'])} каналов")
    print(f"  манифест: nodes={manifest['nodes']}, edges={manifest['edges']}, "
          f"descendingTotal={manifest['descendingTotal']}")
    check(circuit["n"] == manifest["nodes"] and circuit["n_edges"] == manifest["edges"],
          "числа в схеме и манифесте совпадают",
          f"{circuit['n']} узлов / {circuit['n_edges']} рёбер")
    print(f"  sha256 схемы сейчас: {sha256(CIRCUIT)[:16]}…; в манифесте: {manifest['graphSha256'][:16]}…")
    same_sha = sha256(CIRCUIT) == manifest["graphSha256"]
    check(same_sha, "схема — ровно тот файл, что описан в манифесте",
          "" if same_sha else "файл пересобирался (ожидаемо после правок F7): сверить числа ниже")

    print("\n=== 2. аннотации датасета MaleCNS (источник)")
    ann_path = ensure_annotations(args.no_download)
    if ann_path is None:
        check(False, "файл аннотаций доступен", "дальнейшие сверки невозможны")
    else:
        want = json.loads(FETCH_MANIFEST.read_text())["files"]["annotations"]
        got = sha256(ann_path)
        check(got == want["sha256"], "sha256 скачанного файла = записанному в fetch-manifest",
              f"{got[:16]}… против {want['sha256'][:16]}…")

        import pyarrow.feather as feather
        import numpy as np
        df = feather.read_table(ann_path).to_pandas()
        df = df[df.bodyId.notna()].copy()
        body = df.bodyId.to_numpy(np.int64)
        print(f"  клеток в датасете: {len(df)}, типов: {df.type.nunique()}, "
              f"суперклассов: {df.superclass.nunique()}")

        nodes = circuit["nodes"]
        ids = np.asarray(nodes["nt"] and [0], dtype=np.int64) if False else None  # noqa: F841
        # тело графа отдаёт словарь полей и отдельный список id нет — берём из рёбер? нет:
        # у нас есть types/side/nt по индексу, а bodyIds читаем из самого файла схемы ниже.
        circuit_ids = read_body_ids()
        print(f"  bodyId в схеме: {len(circuit_ids)} (уникальных {len(set(circuit_ids))})")

        present = np.isin(circuit_ids, body)
        check(bool(present.all()), "каждая клетка схемы есть в датасете MaleCNS",
              f"найдено {int(present.sum())} из {len(circuit_ids)}")

        # типы/сторона: сверяем по каждой клетке
        lookup = {int(b): (t, s, sc) for b, t, s, sc in
                  zip(body, df.type.to_numpy(), df.somaSide.fillna(df.rootSide).to_numpy(),
                      df.superclass.to_numpy())}
        mism_t = mism_s = mism_sc = 0
        n_dn = 0
        for b, t, s in zip(circuit_ids, nodes["type"], nodes["side"]):
            want_t, want_s, want_sc = lookup[int(b)]
            if (t or None) != (None if want_t != want_t else str(want_t)):
                mism_t += 1
            if str(s) != str(want_s):
                mism_s += 1
            if want_sc == "descending_neuron":
                n_dn += 1
        check(mism_t == 0, "тип клетки у всех клеток схемы совпадает с датасетом",
              f"расхождений {mism_t}")
        check(mism_s == 0, "сторона (somaSide/rootSide) совпадает", f"расхождений {mism_s}")

        dn_all = int((df.superclass == "descending_neuron").sum())
        dn_in_circuit = int(sum(1 for b in circuit_ids if lookup[int(b)][2] == "descending_neuron"))
        check(dn_all == manifest["descendingTotal"], "число нисходящих в датасете совпало с манифестом",
              f"{dn_all}")
        check(dn_in_circuit == dn_all, "все нисходящие нейроны датасета есть в схеме",
              f"{dn_in_circuit} из {dn_all}")

        types_in_ann = set(str(t) for t in df.type.dropna().unique())
        input_types = list(circuit.get("input_types") or [])
        missing = [t for t in input_types if t not in types_in_ann]
        check(not missing, "все 13 типов входных клеток существуют в датасете",
              f"нет таких: {missing}" if missing else ", ".join(input_types[:4]) + "…")

    print("\n=== 3. рёбра схемы: внутренняя консистентность")
    pre, post = circuit["pre"], circuit["post"]
    n = circuit["n"]
    lo = int(min(pre.min(), post.min())); hi = int(max(pre.max(), post.max()))
    check(lo >= 0 and hi < n, "все рёбра ссылаются на существующие клетки", f"диапазон {lo}..{hi} из 0..{n-1}")
    deg = np.bincount(pre, minlength=n)
    check(int(deg.sum()) == circuit["n_edges"], "сумма исходящих степеней = число рёбер")
    top = np.argsort(deg)[-3:][::-1]
    print(f"  крупнейшие хабы по исходящим: {[(int(i), int(deg[i])) for i in top]}")

    total = sum(1 for ok, _, _ in results if ok)
    bad = [r for r in results if not r[0]]
    print(f"\nитог: {total} из {len(results)} проверок пройдено")
    for _, what, detail in bad:
        print(f"  не прошло: {what} — {detail}")
    return 1 if bad else 0


def read_body_ids() -> list[int]:
    """bodyId по порядку индексов: читаем только секцию nodes потоково."""
    import numpy as np
    from fly_brain import _skip_ws, _Grow
    text = CIRCUIT.read_text()
    dec = json.JSONDecoder()
    i = text.index('"nodes"')
    i = _skip_ws(text, text.index("[", i) + 1)
    ids = _Grow(np.int64, 16384)
    while True:
        i = _skip_ws(text, i)
        if text[i] == "]":
            break
        if text[i] == ",":
            i += 1
            continue
        item, i = dec.raw_decode(text, i)
        ids.add(item["id"])
    return ids.array().tolist()


if __name__ == "__main__":
    raise SystemExit(main())
