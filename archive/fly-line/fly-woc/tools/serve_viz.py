#!/usr/bin/env python3
"""Показать наши клетки в Neuroglancer — чужом готовом вьюере, без своего рендера.

Два режима:

  # 1) Свой локальный вьюер (лучший вариант: ничего не хостится, состояние
  #    отдаётся вьюеру напрямую). Требует `pip install neuroglancer`.
  python3 tools/serve_viz.py --viewer --scene viz/scene-full.json

  # 2) Статический сервер с CORS — раздаёт сцену, которую читает публичный
  #    клиент neuroglancer-demo.appspot.com по URL.
  python3 tools/serve_viz.py --scene viz/scene-full.json

Почему нужен CORS: клиент Neuroglancer всегда открывается на чужом домене
(neuroglancer-demo.appspot.com), а состояние тянет с нашего адреса — без заголовка
Access-Control-Allow-Origin браузер такую загрузку запретит.

Данные слоёв (ЭМ-объём, сегментация, меши) не хостятся у нас вообще: сцена
ссылается на публичные precomputed-источники Janelia (gs://flyem-male-cns),
их отдаёт Google Storage с открытым CORS.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import socketserver
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class CorsHandler(http.server.SimpleHTTPRequestHandler):
    """Отдаёт файлы с CORS, чтобы сцену можно было читать с чужого домена."""

    def end_headers(self) -> None:  # noqa: D102
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # тише в логе
        if "200" not in (fmt % args):
            super().log_message(fmt, *args)


def run_viewer(scene: Path, host: str = "127.0.0.1", port: int = 0) -> int:
    try:
        import neuroglancer
    except ImportError:
        print("нет модуля neuroglancer: pip install neuroglancer", file=sys.stderr)
        return 2
    if host != "127.0.0.1" or port:
        # по умолчанию вьюер слушает только localhost; наружу нужен явный bind
        neuroglancer.set_server_bind_address(bind_address=host, bind_port=port)
    viewer = neuroglancer.Viewer()
    viewer.set_state(json.loads(scene.read_text()))
    url = viewer.get_viewer_url()
    print(f"сцена: {scene}")
    print(f"открой в браузере: {url}")
    print("(Ctrl+C — остановить)")
    try:
        while True:  # держим сервер вьюера живым; состояние уже отдано
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nостановлено")
    return 0


def run_server(scene: Path, port: int, host: str) -> int:
    directory = str(scene.parent)
    handler = functools.partial(CorsHandler, directory=directory)

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server((host, port), handler) as httpd:
        name = scene.name
        print(f"раздаю {directory} на http://{host}:{port}")
        print("открой один из адресов (нужен WebGL):")
        print(f"  https://neuroglancer-demo.appspot.com/#!http://localhost:{port}/{name}")
        print(f"  http://neuroglancer-demo.appspot.com/#!http://localhost:{port}/{name}")
        print("если пусто — используй режим --viewer (надёжнее)")
        print("Ctrl+C — остановить")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nостановлено")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scene", default=str(ROOT / "viz" / "scene-full.json"))
    ap.add_argument("--port", type=int, default=8790, help="порт (для --viewer: 0 = любой свободный)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--viewer", action="store_true", help="свой локальный вьюер вместо статики")
    args = ap.parse_args()

    scene = Path(args.scene)
    if not scene.exists():
        print(f"нет файла сцены {scene}; сначала: python3 tools/viz_export.py", file=sys.stderr)
        return 1
    if args.viewer:
        return run_viewer(scene, args.host, args.port)
    return run_server(scene, args.port, args.host)


if __name__ == "__main__":
    sys.exit(main())
