"""device_utils.py — единственное место, где выбирается устройство вычислений.

Порядок выбора: аргумент --device → переменная WOC_DEVICE → cuda → mps → cpu.

Кроме CUDA и Apple MPS поддерживается ROCm (AMD): torch на ROCm вызывает своё
устройство «cuda», и это единственное отличие — поэтому алиасы rocm/hip/amdgpu
ведут туда же, а различает их torch.version.hip. Для ROCm дополнительно:
  * в описании устройства печатается gfx-таргет (props.gcnArchName) — именно он
    показывает, что HSA_OVERRIDE_GFX_VERSION=10.3.0 действительно применился и
    карта RDNA2 (например RX 6750 XT, физически gfx1031) считается как gfx1030;
  * включается PYTORCH_HIP_ALLOC_CONF=expandable_segments:True, если переменная
    не задана: на 12 ГБ карты фрагментация — реальная причина OOM при живом
    свободном объёме;
  * число потоков CPU-части задаётся WOC_THREADS (иначе — решение torch).

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
    "rocm": "cuda", "hip": "cuda", "amdgpu": "cuda",   # ROCm в torch — это device "cuda"
    "mps": "mps", "metal": "mps", "cpu": "cpu",
}


def is_rocm() -> bool:
    """Сборка torch под ROCm (AMD). У неё torch.version.cuda = None, а hip заполнен."""
    return getattr(torch.version, "hip", None) is not None


def hsa_override() -> str | None:
    """Значение HSA_OVERRIDE_GFX_VERSION, если карта «прикидывается» более старой."""
    return os.environ.get("HSA_OVERRIDE_GFX_VERSION") or None


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
        dev = torch.device(want)
        apply_device_hints(dev)
        apply_thread_settings()
        return dev
    for candidate in ("cuda", "mps"):
        if device_available(candidate):
            dev = torch.device(candidate)
            apply_device_hints(dev)
            apply_thread_settings()
            return dev
    apply_thread_settings()
    return torch.device("cpu")


def describe_device(dev: torch.device | str) -> str:
    d = torch.device(dev)
    if d.type == "cuda":
        index = d.index if d.index is not None else torch.cuda.current_device()
        props = torch.cuda.get_device_properties(index)
        name = torch.cuda.get_device_name(index)
        total = props.total_memory / 1024**3
        if is_rocm():
            # gcnArchName — то, что реально увидела runtime: при включённом
            # HSA_OVERRIDE_GFX_VERSION здесь будет gfx-таргет из переменной, а не
            # физический (у RX 6750 XT физически gfx1031, а с override — gfx1030).
            arch = getattr(props, "gcnArchName", None) or "gfx?"
            extra = f", HSA_OVERRIDE_GFX_VERSION={hsa_override()}" if hsa_override() else ""
            return (f"cuda:{index} {name} ({total:.1f} ГБ, ROCm/HIP {torch.version.hip}, "
                    f"{arch}{extra})")
        cap = torch.cuda.get_device_capability(index)
        return f"cuda:{index} {name} ({total:.1f} ГБ, sm_{cap[0]}{cap[1]})"
    if d.type == "mps":
        return "mps (Apple Silicon)"
    return "cpu"


def apply_thread_settings() -> int:
    """Сколько потоков отдано CPU-части (torch intra-op).

    Зачем трогать: на CPU-бэкенде схемы (scipy) потоки не помогают вовсе —
    scipy.sparse держит GIL, замерено: 2 потока дали 1.03x, 4 потока 0.50x.
    А вот на GPU-прогонах CPU-часть — это признаки, оракул и PPO-обновление, и
    лишние потоки там только мешают друг другу (упирается в память). Поэтому
    по умолчанию ничего не меняем, но WOC_THREADS=N — явный руль.
    """
    want = os.environ.get("WOC_THREADS")
    if want:
        try:
            n = max(1, int(want))
        except ValueError:
            n = torch.get_num_threads()
        torch.set_num_threads(n)
    return torch.get_num_threads()


def apply_device_hints(dev: torch.device) -> None:
    """Настройки рантайма, которые нельзя выставить после первой аллокации."""
    if dev.type == "cuda" and is_rocm():
        # Фрагментация памяти — реальный источник OOM на 12 ГБ картах при
        # обучении с буферами разного размера. Переменная читается аллокатором
        # один раз, поэтому выставляем её до первого выделения памяти.
        os.environ.setdefault("PYTORCH_HIP_ALLOC_CONF", "expandable_segments:True")


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
        "rocm_build": getattr(torch.version, "hip", None),
        "hsa_override": hsa_override(),
        "hip_alloc_conf": os.environ.get("PYTORCH_HIP_ALLOC_CONF"),
        "torch_threads": torch.get_num_threads(),
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
            "capability": (getattr(props, "gcnArchName", None) or f"{props.major}.{props.minor}"),
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
