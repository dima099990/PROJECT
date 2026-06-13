"""Детект ОС и железа + выбор лучшего вычислительного бэкенда.
Все тяжёлые импорты ленивые/защищённые — модуль не падает без torch/openvino.
Приоритет: CUDA → ROCm → MPS(Apple) → OpenVINO(Intel NPU/GPU) → CPU."""
from __future__ import annotations
import platform


def _os() -> dict:
    return {"system": platform.system(), "release": platform.release(),
            "machine": platform.machine(), "python": platform.python_version()}


def _cpu_ram() -> dict:
    try:
        import psutil
        return {"cores": psutil.cpu_count(logical=True),
                "ram_total_gb": round(psutil.virtual_memory().total / 1073741824, 1)}
    except Exception:
        return {"cores": None, "ram_total_gb": None}


def _torch_gpus() -> list[dict]:
    gpus = []
    try:
        import torch
    except Exception:
        return gpus
    try:
        if getattr(torch.version, "hip", None) and torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                gpus.append({"backend": "rocm", "name": torch.cuda.get_device_name(i),
                             "vram_gb": round(torch.cuda.get_device_properties(i).total_memory / 1073741824, 1)})
        elif torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                gpus.append({"backend": "cuda", "name": torch.cuda.get_device_name(i),
                             "vram_gb": round(torch.cuda.get_device_properties(i).total_memory / 1073741824, 1)})
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            gpus.append({"backend": "mps", "name": "Apple GPU", "vram_gb": None})
    except Exception:
        pass
    return gpus


def _openvino_devices() -> list[dict]:
    out = []
    try:
        import openvino as ov
        core = ov.Core()
        for d in core.available_devices:  # CPU, GPU, NPU, ...
            if d == "CPU":
                continue
            try:
                name = core.get_property(d, "FULL_DEVICE_NAME")
            except Exception:
                name = d
            out.append({"backend": "openvino", "device": d, "name": str(name)})
    except Exception:
        pass
    return out


def detect() -> dict:
    os_i = _os()
    accels = _torch_gpus() + _openvino_devices()
    backend, quant = _choose(accels)
    return {"os": os_i, **_cpu_ram(), "accelerators": accels,
            "backend": backend, "quant": quant}


def _choose(accels: list[dict]) -> tuple[str, str]:
    kinds = {a.get("backend") for a in accels}
    if "cuda" in kinds:
        return "cuda", "int4-bnb"
    if "rocm" in kinds:
        return "rocm", "fp16"
    if "mps" in kinds:
        return "mps", "fp16"
    if any(a.get("device") in ("NPU", "GPU") for a in accels if a.get("backend") == "openvino"):
        return "openvino", "int4-ov"
    return "cpu", "int8"


def best_backend() -> str:
    return detect()["backend"]
