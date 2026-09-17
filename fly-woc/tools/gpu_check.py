#!/usr/bin/env python3
"""gpu_check.py — проверка устройства на ЭТОЙ машине: что выбрано, что пойдёт в дело.

Запускать там, где предполагается GPU (Windows/Linux, torch с CUDA):

    python tools/gpu_check.py                      # обзор
    python tools/gpu_check.py --device cpu         # проверить, что CPU-путь жив
    WOC_DEVICE=cuda python tools/gpu_check.py      # строгая проверка CUDA
    python tools/gpu_check.py --bench              # замер шага схемы на устройстве

Код возврата 1, если запрошенное устройство недоступно (никакого тихого отката).
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from device_utils import (device_available, device_info, describe_device,   # noqa: E402
                          describe_devices, resolve_device)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--device", default=None, help="cuda | cuda:0 | mps | cpu | auto (иначе WOC_DEVICE)")
    p.add_argument("--bench", action="store_true", help="замерить шаг схемы и шаг обучения")
    p.add_argument("--steps", type=int, default=10)
    p.add_argument("--batch", type=int, default=4)
    args = p.parse_args()

    info = device_info()
    print(f"torch {info['torch']} (сборка CUDA: {info['cuda_build'] or 'нет — это CPU-сборка torch'})")
    print(f"cuda: {info['cuda_available']}, mps: {info['mps_available']}, "
          f"доступно: {describe_devices()}, WOC_DEVICE={info['requested_by_env']!r}")
    for entry in info.get("cuda_devices") or []:
        if isinstance(entry, dict):
            cap = entry.get("capability")
            print(f"  cuda:{entry.get('index', '?')} {entry.get('name')}"
                  + (f", {entry['memory_gb']:.0f} ГБ" if entry.get("memory_gb") else "")
                  + (f", sm {cap}" if cap else ""))
        else:
            print(f"  {entry}")
    if not info["cuda_available"] and (args.device or "").lower().startswith("cuda"):
        print("\nВНИМАНИЕ: просят cuda, но torch её не видит. Проверь сборку torch "
              "(pip install torch --index-url https://download.pytorch.org/whl/cu121) и драйвер.")

    if args.device is not None:
        import os
        os.environ["WOC_DEVICE"] = args.device
    try:
        dev = resolve_device()
    except RuntimeError as exc:
        print(f"\nОШИБКА: {exc}")
        return 1
    print(f"\nвыбрано: {describe_device(dev)}")
    if dev.type == "cuda" and not device_available("cuda"):
        print("внутренняя несогласованность: выбрана cuda, а её нет")
        return 1

    from fly_brain import FlyBrain
    brain = FlyBrain(device=str(dev))
    print(f"{brain.describe()}")
    if brain.device != dev and str(brain.device) != str(dev):
        print(f"ВНИМАНИЕ: мозг считает на {brain.device}, а выбрано {dev} — "
              f"схема и читаут разъедутся")
        return 1
    if str(brain.backend) == "scipy" and dev.type != "cpu":
        print("ВНИМАНИЕ: scipy-бэкенд на не-CPU устройстве — не имеет смысла")
        return 1

    if not args.bench:
        print("\nок; замер: --bench")
        return 0

    import torch
    torch.manual_seed(0)
    feats = torch.rand(args.batch, 13, device=dev if isinstance(dev, torch.device) else str(dev))
    warm = 2
    times: list[float] = []
    for i in range(warm + args.steps):
        if str(dev).startswith("cuda"):
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        brain.step(feats)
        if str(dev).startswith("cuda"):
            torch.cuda.synchronize()      # без синхронизации замер врёт: ядро только поставлено в очередь
        dt = time.perf_counter() - t0
        if i >= warm:
            times.append(dt * 1000.0)
    med = statistics.median(times)
    print(f"шаг схемы ({brain.backend}, B={args.batch}): медиана {med:.1f} мс "
          f"(мин {min(times):.1f}, макс {max(times):.1f}; среда с frameSkip 5 ~ 200 мс/шаг — "
          f"{'успевает' if med < 200 else 'НЕ успевает'})")
    dev_type = getattr(brain.device, "type", str(brain.device))
    if dev_type == "cuda":
        print(f"память CUDA: выделено {torch.cuda.memory_allocated()/2**20:.0f} МБ, "
              f"пик {torch.cuda.max_memory_allocated()/2**20:.0f} МБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
