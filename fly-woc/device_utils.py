"""device_utils.py — единственное место, где выбирается устройство вычислений.

Порядок выбора: аргумент --device → переменная WOC_DEVICE → cuda → mps → cpu.

Почему отдельный модуль: прежний код выбирал устройство в четырёх разных местах
(train.py, flybrain_8k_gpu.py, live_agent.py, src/fly_brain/engine.py) и в
активной схеме (fly_brain.py) параметр device вообще не использовался — схема
считалась на CPU, а «GPU» оставался только в названиях файлов.

Явно запрошенное, но недоступное устройство — ошибка, а не тихий откат на CPU:
молчаливый фолбэк уже один раз стоил дней счёта не там, где планировалось.
"""
from __future__ import annotations

import os

import torch

_ALIASES = {
    "": None, "auto": None, "gpu": "cuda", "cuda": "cuda",
    "mps": "mps", "metal": "mps", "cpu": "cpu",
}


def requested_device(prefer: str | None = None) -> str | None:
    """Что просили: аргумент, иначе WOC_DEVICE. None = «решай сам»."""
    for candidate in (prefer, os.environ.get("WOC_DEVICE")):
        if candidate is None:
            continue
        key = str(candidate).strip().lower()
        resolved = _ALIASES.get(key, key)
        if resolved:
            return resolved
    return None


def device_available(name: str) -> bool:
    if name.startswith("cuda"):
        return torch.cuda.is_available()
    if name == "mps":
        backend = getattr(torch.backends, "mps", None)
        return bool(backend is not None and backend.is_available())
    return name == "cpu"


def resolve_device(prefer: str | None = None, *, strict: bool = True) -> torch.device:
    """torch.device для работы. Строгий режим: нет устройства — падаем, а не молчим."""
    want = requested_device(prefer)
    if want is not None and not device_available(want):
        details = describe_devices()
        if strict:
            raise RuntimeError(
                f"запрошено устройство {want!r} (WOC_DEVICE={os.environ.get('WOC_DEVICE')!r}), "
                f"но оно недоступно. Доступно: {details}. "
                f"Убери запрос устройства или установи GPU-сборку torch."
            )
        want = None
    if want is not None:
        return torch.device(want)
    for candidate in ("cuda", "mps"):
        if device_available(candidate):
            return torch.device(candidate)
    return torch.device("cpu")


def describe_device(dev: torch.device | str) -> str:
    d = torch.device(dev)
    if d.type == "cuda":
        index = d.index if d.index is not None else torch.cuda.current_device()
        name = torch.cuda.get_device_name(index)
        total = torch.cuda.get_device_properties(index).total_memory / 1024**3
        cap = torch.cuda.get_device_capability(index)
        return f"cuda:{index} {name} ({total:.1f} ГБ, sm_{cap[0]}{cap[1]})"
    if d.type == "mps":
        return "mps (Apple Silicon)"
    return "cpu"


def describe_devices() -> str:
    parts = []
    if torch.cuda.is_available():
        parts += [describe_device(f"cuda:{i}") for i in range(torch.cuda.device_count())]
    if device_available("mps"):
        parts.append("mps")
    parts.append("cpu")
    return ", ".join(parts)


def device_info() -> dict:
    """Сводка для логов и tools/gpu_check.py."""
    info = {
        "torch": torch.__version__,
        "cuda_build": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "mps_available": device_available("mps"),
        "requested_by_env": os.environ.get("WOC_DEVICE"),
        "devices": describe_devices(),
        "cuda_devices": [],
    }
    for i in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(i)
        info["cuda_devices"].append({
            "index": i,
            "name": props.name,
            "total_gb": round(props.total_memory / 1024**3, 1),
            "capability": f"{props.major}.{props.minor}",
            "bf16": bool(getattr(props, "is_bf16_supported", lambda: False)()),
        })
    return info


def to_device(value, device: torch.device, dtype: torch.dtype | None = None):
    """Перенос numpy/списка/тензора на устройство — одним вызовом, без копий на CPU."""
    if isinstance(value, torch.Tensor):
        out = value if value.device == device else value.to(device, non_blocking=True)
    else:
        out = torch.as_tensor(value, device=device)
    if dtype is not None and out.dtype != dtype:
        out = out.to(dtype)
    return out
