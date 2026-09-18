#!/usr/bin/env python3
"""gpu_check.py — проверка устройства на ЭТОЙ машине: что выбрано, что пойдёт в дело.

Запускать там, где предполагается GPU (Windows/Linux, torch с CUDA или ROCm):

    python tools/gpu_check.py                      # обзор
    python tools/gpu_check.py --device cpu         # проверить, что CPU-путь жив
    WOC_DEVICE=cuda python tools/gpu_check.py      # строгая проверка CUDA/ROCm
    python tools/gpu_check.py --bench              # замер шага схемы на устройстве
    python tools/gpu_check.py --bench-backends     # какой бэкенд быстрее НА ЭТОЙ карте

Код возврата 1, если запрошенное устройство недоступно (никакого тихого отката).

AMD/ROCm (в том числе RX 6750 XT, gfx1031, с HSA_OVERRIDE_GFX_VERSION=10.3.0):
torch на ROCm называет устройство «cuda», поэтому --device cuda — это оно и есть.
Строка «ROCm/HIP …» и gfx-таргет в выводе ниже показывают, что runtime поднялся.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from device_utils import (describe_device, describe_devices, device_available,   # noqa: E402
                          device_info, is_rocm, resolve_device)


def print_device_report(info: dict) -> None:
    if info.get("rocm_build"):
        print(f"torch {info['torch']} (сборка ROCm/HIP {info['rocm_build']} — AMD)")
    elif info["cuda_build"]:
        print(f"torch {info['torch']} (сборка CUDA {info['cuda_build']})")
    else:
        print(f"torch {info['torch']} (CPU-сборка: ни CUDA, ни ROCm)")
    print(f"cuda(в т.ч. ROCm): {info['cuda_available']}, mps: {info['mps_available']}, "
          f"доступно: {describe_devices()}, WOC_DEVICE={info['requested_by_env']!r}")
    print(f"потоков у torch: {info['torch_threads']} (руль — WOC_THREADS)")
    if info.get("hsa_override"):
        print(f"HSA_OVERRIDE_GFX_VERSION={info['hsa_override']}: gfx-таргет ниже — это то, "
              f"во что превратили карту, а не её физическая архитектура")
    if info.get("hip_alloc_conf"):
        print(f"PYTORCH_HIP_ALLOC_CONF={info['hip_alloc_conf']}")
    for entry in info.get("cuda_devices") or []:
        if isinstance(entry, dict):
            arch = entry.get("capability")
            label = f"{arch}" if arch and str(arch).startswith("gfx") else (f"sm {arch}" if arch else "")
            print(f"  cuda:{entry.get('index', '?')} {entry.get('name')}"
                  + (f", {entry['total_gb']:.0f} ГБ" if entry.get("total_gb") else "")
                  + (f", {label}" if label else ""))
        else:
            print(f"  {entry}")


def explain_missing(info: dict, asked: str | None) -> None:
    if info["cuda_available"] or not (asked or "").lower().startswith("cuda"):
        return
    print("\nВНИМАНИЕ: просят cuda, но torch её не видит.")
    if info.get("rocm_build"):
        print("  Сборка ROCm есть, значит проблема не в пакете, а в доступе к устройству:\n"
              "  Linux: /dev/kfd и /dev/dri доступны? пользователь в группах render/video?\n"
              "  Windows: HIP SDK установлен, драйвер не ниже требуемого?\n"
              "  Для карт RDNA2 вне списка поддержки (RX 6750 XT = gfx1031) нужен\n"
              "  HSA_OVERRIDE_GFX_VERSION=10.3.0 — выставить в той же оболочке.")
    elif info["cuda_build"]:
        print("  Сборка CUDA на месте, но устройство недоступно: проверь драйвер и видимость GPU.")
    else:
        print("  Это CPU-сборка torch. Нужен GPU-пакет:\n"
              "  NVIDIA: pip install torch --index-url https://download.pytorch.org/whl/cu121\n"
              "  AMD: pip install torch --index-url https://download.pytorch.org/whl/rocm6.2\n"
              "       (для RDNA2 вне списка поддержки — плюс HSA_OVERRIDE_GFX_VERSION=10.3.0)")


def bench_backends(dev, args) -> int:
    """Замер всех бэкендов схемы на выбранном устройстве + сверка с CPU-эталоном.

    Смысл: «edge быстрее sparse» — это вывод из замера на CPU. На конкретной карте
    порядок может быть другим (ROCm считает CSR нативно, gather/index_add упирается
    в пропускную способность памяти), поэтому бэкенд выбирает не догадка, а этот замер.
    """
    import os

    import numpy as np
    import torch

    from fly_brain import FlyBrain

    batch = args.batch
    formats = [("scipy", {}), ("edge", {})]
    if dev.type == "cuda":
        formats.append(("sparse", {}))
        if not getattr(args, "no_coo", False):
            formats.append(("sparse", {"WOC_SPARSE_FORMAT": "coo"}))
    else:
        formats.append(("sparse", {}))

    feats = torch.rand(batch, 13)
    ref = None
    rows = []
    for backend, env in formats:
        for k, v in env.items():
            os.environ[k] = v
        try:
            brain = FlyBrain(device=dev, backend=backend)
        finally:
            for k in env:
                os.environ.pop(k, None)
        brain.reset(batch)
        is_cpu_ref = backend == "scipy"
        x = feats.cpu() if is_cpu_ref else feats.to(dev)
        brain.step(x)
        time.sleep(0)                      # не дать планировщику «схлопнуть» прогрев
        for _ in range(3):
            brain.step(x)
        times = []
        for _ in range(args.steps):
            if dev.type == "cuda":
                torch.cuda.synchronize()
            t0 = time.perf_counter()
            brain.step(x)
            if dev.type == "cuda":
                torch.cuda.synchronize()
            times.append((time.perf_counter() - t0) * 1000.0)
        med = statistics.median(times)
        got = brain.step(x).detach().to("cpu").float().numpy()
        if ref is None:
            ref = got
        diff = float(np.abs(got - ref).max())
        label = backend + ("(coo)" if env.get("WOC_SPARSE_FORMAT") == "coo" else "")
        rows.append((label, med, min(times), diff))
        del brain

    print(f"\n=== бэкенды схемы на {describe_device(dev)}, B={batch}, {args.steps} шагов")
    print("| бэкенд | медиана, мс | мин, мс | max|Δ| против scipy |")
    print("|---|---|---|---|")
    for label, med, mn, diff in rows:
        print(f"| {label} | {med:.2f} | {mn:.2f} | {diff:.2e} |")
    fast = min(rows, key=lambda r: r[1])
    print(f"\nбыстрее всех: {fast[0]} ({fast[1]:.2f} мс/шаг). "
          f"Среда с frameSkip 5 даёт ~200 мс на шаг — {'успевает' if fast[1] < 200 else 'НЕ успевает'}.")
    print("Выбор: --backend scipy|edge|sparse у train.py / progress_eval.py, "
          "либо WOC_BRAIN_BACKEND=<имя>. "
          "Расхождение с scipy больше 1e-5 — не «шум», а другой ответ: разбирайся, "
          "не выбирай по скорости.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--device", default=None, help="cuda | cuda:0 | rocm | mps | cpu | auto (иначе WOC_DEVICE)")
    p.add_argument("--bench", action="store_true", help="замерить шаг схемы и шаг обучения")
    p.add_argument("--bench-backends", action="store_true", help="сравнить бэкенды схемы на этом устройстве")
    p.add_argument("--no-coo", action="store_true", help="в --bench-backends не проверять и COO-формат")
    p.add_argument("--steps", type=int, default=10)
    p.add_argument("--batch", type=int, default=4)
    p.add_argument("--threads", type=int, default=None, help="то же, что WOC_THREADS (потоки CPU-части)")
    args = p.parse_args()

    if args.threads:
        import os
        os.environ["WOC_THREADS"] = str(args.threads)

    info = device_info()
    print_device_report(info)
    explain_missing(info, args.device)

    if args.device is not None:
        import os
        os.environ["WOC_DEVICE"] = args.device
    try:
        dev = resolve_device()
    except RuntimeError as exc:
        print(f"\nОШИБКА: {exc}")
        return 1
    print(f"\nвыбрано: {describe_device(dev)}")
    if args.threads:
        print(f"потоков у torch: {__import__('torch').get_num_threads()}")
    if dev.type == "cuda" and not device_available("cuda"):
        print("внутренняя несогласованность: выбрана cuda, а её нет")
        return 1

    if args.bench_backends:
        return bench_backends(dev, args)

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
        print("\nок; замер: --bench, выбор бэкенда: --bench-backends")
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
        alloc = "память CUDA" if not is_rocm() else "память HIP"
        print(f"{alloc}: выделено {torch.cuda.memory_allocated()/2**20:.0f} МБ, "
              f"пик {torch.cuda.max_memory_allocated()/2**20:.0f} МБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
