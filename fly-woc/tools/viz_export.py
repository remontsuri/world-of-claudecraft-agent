#!/usr/bin/env python3
"""Сцены Neuroglancer для нашей схемы: наши клетки внутри настоящего MaleCNS.

Зачем: в интернете уже есть готовые вьюеры MaleCNS (Neuroglancer, neuPrint, Codex,
Cell Type Explorer, VFB). Рисовать свой 3D-рендер не нужно — нужно вставить свои
клетки в официальный вьюер. У каждой клетки нашей схемы в data/circuit.json лежит
настоящий bodyId MaleCNS, поэтому это делается без единого запроса к API и без
токена: берём официальную сцену Janelia, ставим в неё свои сегменты и точки сом.

Что получается на выходе:
  viz/scene-full.json   — вся схема (8835 сом точками по ролям) + 82 выходных DN
                          мешами, поверх настоящей ЭМ-объём, оболочек нейропилей;
  viz/scene-dn82.json   — лёгкая сцена: только 82 выходных нисходящих (меши + сомы);
  viz/links.md          — прямые ссылки на наши клетки в чужих вьюерах (VFB,
                          neuPrint, Codex MCNS, Cell Type Explorer).

Сцена открывается: `python3 tools/serve_viz.py` (локальный вьюер) либо любой
клиент Neuroglancer, умеющий читать состояние по URL (нужен CORS → serve_viz.py).

Оговорка про данные: координаты сомы берутся из публичного файла аннотаций
MaleCNS (14 МБ, CC BY 4.0, скачивается автоматически). Если файла нет и сеть
недоступна — сцена собирается без слоя сом (останется список сегментов).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

OFFICIAL_SCENE_URL = "https://storage.googleapis.com/flyem-male-cns/v1.0/male-cns-v1.0.json"
ANN_BASE = "https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome"
ANN_NAME = "body-annotations-male-cns-v1.0-minconf-0.5.feather"

# какие официальные слои оставляем в сцене (остальные 40+ архивных не тащим)
KEEP_LAYERS = (
    "em-clahe",                     # настоящий ЭМ-объём
    "cns-seg",                      # сегментация: меши наших клеток
    "brain-neuropil-shell",
    "vnc-neuropil-shell",
    "major-compartments",
)

ROLE_STYLE = {
    "descending": ("#ff3b30", "нисходящие (моторный выход мухи)"),
    "input": ("#34c759", "входные клетки (13 каналов)"),
    "interneuron": ("#8e8e93", "внутренние (промежуточные)"),
}
OUT_COLOR = "#ff9500"  # 82 выхода, которыми играет агент


def load_json(path: Path) -> dict:
    with path.open() as fh:
        return json.load(fh)


def find_annotations(explicit: str | None, no_download: bool) -> Path | None:
    """Ищем файл аннотаций MaleCNS; при отсутствии — качаем (14 МБ, публично)."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates += [
        Path(__file__).resolve().parent.parent / "data" / "malecns" / ANN_NAME,
        Path.home() / "data" / "malecns" / ANN_NAME,
        Path("/home/user/malecns-verify") / ANN_NAME,
    ]
    for c in candidates:
        if c.exists():
            return c
    if no_download:
        return None
    dst = Path(__file__).resolve().parent.parent / "data" / "malecns" / ANN_NAME
    dst.parent.mkdir(parents=True, exist_ok=True)
    url = f"{ANN_BASE}/{ANN_NAME}"
    print(f"  качаю аннотации: {url}")
    try:
        urllib.request.urlretrieve(url, dst)  # noqa: S310 (публичный CC-BY файл)
    except Exception as exc:  # сеть/диск — не повод падать, соберём без сом
        print(f"  ВНИМАНИЕ: не скачалось ({exc}); сцена будет без слоёв сом")
        return None
    return dst


def soma_table(ann_path: Path | None, ids: list[int]) -> dict[int, tuple[int, int, int]]:
    if ann_path is None:
        return {}
    import pandas as pd

    df = pd.read_feather(ann_path)[["bodyId", "somaLocation"]]
    df = df[df.bodyId.isin(ids)]
    out: dict[int, tuple[int, int, int]] = {}
    for body, loc in zip(df.bodyId.to_numpy(), df.somaLocation.to_numpy()):
        if loc is None:
            continue
        x, y, z = (int(v) for v in loc[:3])
        out[int(body)] = (x, y, z)
    return out


def annotation_layer(name: str, color: str, cells: list[dict], somas: dict) -> dict:
    """Слой точек: одна точка на клетку, в описании — тип/роль/настоящий bodyId."""
    anns = []
    for cell in cells:
        pos = somas.get(cell["id"])
        if pos is None:
            continue
        anns.append(
            {
                "point": [float(pos[0]), float(pos[1]), float(pos[2])],
                "description": f"{cell['type']} {cell['side']} · bodyId {cell['id']} · {cell['role']}",
            }
        )
    return {
        "type": "annotation",
        "name": name,
        "annotationColor": color,
        "annotationOpacity": 0.85,
        "annotations": anns,
        "visible": True,
    }


def build_scene(official: dict, cells: list[dict], somas: dict, out_ids: list[int], title: str) -> dict:
    layers = [dict(layer) for layer in official["layers"] if layer.get("name") in KEEP_LAYERS]
    seg = next(layer for layer in layers if layer["name"] == "cns-seg")
    seg["segments"] = [str(b) for b in out_ids]
    seg["segmentColors"] = {str(b): OUT_COLOR for b in out_ids}
    seg["segmentDefaultColor"] = "#c8c8c8"
    seg["visible"] = True
    # меши в 3D подгружаются только для выделенных сегментов, поэтому сцена лёгкая
    for layer in layers:
        if layer["name"] != "cns-seg":
            layer["visible"] = layer["name"] == "em-clahe"
    for role in ("interneuron", "descending", "input"):
        color, _label = ROLE_STYLE[role]
        layers.append(annotation_layer(
            f"our-somas-{role}", color,
            [c for c in cells if c["role"] == role], somas))
    positions = [somas[c["id"]] for c in cells if c["role"] == "descending" and c["id"] in somas]
    if positions:
        n = len(positions)
        center = [sum(p[i] for p in positions) / n for i in range(3)]
    else:
        center = list(official["position"])
    scene = dict(official)
    scene["layers"] = layers
    scene["title"] = title
    scene["position"] = center
    scene["crossSectionScale"] = 400.0   # обзор всего ЦНС, а не одного нейропиля
    scene["projectionScale"] = 6000.0
    return scene


def links_md(cells: list[dict], out_ids: list[int], ann_meta: dict) -> str:
    by_id = {c["id"]: c for c in cells}
    lines = [
        "# Прямые ссылки в чужие вьюеры (наши клетки = настоящие bodyId MaleCNS)",
        "",
        "У всех клеток схемы `id` — это настоящий `bodyId` датасета MaleCNS v1.0,",
        "поэтому любую из них можно открыть в официальных инструментах Janelia.",
        "",
        "## 82 выходные нисходящие (ими играет агент)",
        "",
        "| тип | сторона | bodyId | VFB | neuPrint | Codex MCNS |",
        "|---|---|---|---|---|---|",
    ]
    for body in out_ids:
        cell = by_id[body]
        vfb = ann_meta.get(body, {}).get("vfbId") or ""
        vfb_cell = f"[открыть](https://virtualflybrain.org/reports/{vfb})" if vfb else "—"
        np_url = (
            "https://neuprint.janelia.org/results?dataset=male-cns%3Av1.0&q=1&qt=findneurons"
            "&qr%5B0%5D%5Bcode%5D=sk&qr%5B0%5D%5Bds%5D=male-cns%3Av1.0"
            "&qr%5B0%5D%5Bpm%5D%5BdataSet%5D=male-cns%3Av1.0&qr%5B0%5D%5Bpm%5D%5Bskip%5D=true"
            f"&qr%5B0%5D%5Bpm%5D%5BbodyIds%5D={body}&tab=1"
        )
        cx_url = f"https://codex.flywire.ai/?dataset=mcns&query={cell['type']}"
        lines.append(
            f"| {cell['type']} | {cell['side']} | {body} | {vfb_cell} | [skeleton]({np_url}) | [поиск]({cx_url}) |"
        )
    lines += [
        "",
        "## Что открыть целиком",
        "",
        "- Официальная сцена MaleCNS (ЭМ + сегментация + нейропили, поиск по типу клетки):",
        "  https://neuroglancer-demo.appspot.com/#!gs://flyem-male-cns/v1.0/male-cns-v1.0.json",
        "- Со всеми нашими клетками: `python3 tools/serve_viz.py` → печатает ссылку на сцену.",
        "- neuPrint (интерактивные запросы связности): https://neuprint.janelia.org/?dataset=male-cns%3Av1.0&qt=findneurons",
        "- Codex MCNS (поиск/графы/3D по всей ЦНС): https://codex.flywire.ai/?dataset=mcns",
        "- Cell Type Explorer (каталог типов с eyemap):",
        "  https://reiserlab.github.io/celltype-explorer-drosophila-male-cns/",
        "- VFB (анатомия/литература по клетке): https://virtualflybrain.org/",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--circuit", default=str(root / "data" / "circuit.json"))
    ap.add_argument("--annotations", default=None, help="путь к body-annotations-*.feather")
    ap.add_argument("--out-dir", default=str(root / "viz"))
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--scene", choices=["both", "full", "dn82"], default="both")
    args = ap.parse_args()

    circuit = load_json(Path(args.circuit))
    cells = circuit["nodes"]
    out_ids = [cells[i]["id"] for i in circuit["outputs"]]
    print(f"схема: {len(cells)} клеток, {len(circuit['edges'])} рёбер, выходов {len(out_ids)}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cache = out_dir / "official-scene.json"
    if cache.exists():
        official = load_json(cache)
    else:
        print(f"  качаю официальную сцену: {OFFICIAL_SCENE_URL}")
        with urllib.request.urlopen(OFFICIAL_SCENE_URL, timeout=60) as fh:  # noqa: S310
            official = json.loads(fh.read().decode())
        cache.write_text(json.dumps(official))

    ann_path = find_annotations(args.annotations, args.no_download)
    somas = soma_table(ann_path, [c["id"] for c in cells])
    print(f"сомы: {len(somas)} из {len(cells)}")

    if args.scene in ("both", "full"):
        scene = build_scene(official, cells, somas, out_ids,
                            "World of ClaudeCraft: наша схема (8835 клеток) внутри MaleCNS")
        (out_dir / "scene-full.json").write_text(json.dumps(scene))
    if args.scene in ("both", "dn82"):
        dn82 = [c for c in cells if c["id"] in set(out_ids)]
        scene82 = build_scene(official, dn82, somas, out_ids,
                              "World of ClaudeCraft: 82 выходных нисходящих")
        (out_dir / "scene-dn82.json").write_text(json.dumps(scene82))

    # метаданные для ссылок: vfbId
    ann_meta: dict[int, dict] = {}
    if ann_path is not None:
        import pandas as pd

        df = pd.read_feather(ann_path)[["bodyId", "vfbId"]]
        df = df[df.bodyId.isin(out_ids)]
        ann_meta = {int(b): {"vfbId": v} for b, v in zip(df.bodyId, df.vfbId)}

    (out_dir / "links.md").write_text(links_md(cells, out_ids, ann_meta))
    for f in sorted(out_dir.glob("*.json")):
        print(f"  {f.name}: {f.stat().st_size / 1024:.0f} КБ")
    print(f"  links.md: {len(out_ids)} ссылок")
    return 0


if __name__ == "__main__":
    sys.exit(main())
