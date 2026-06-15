"""Единое инференс-ядро: фасад поверх бэкендов (torch: cuda/rocm/mps/cpu;
openvino: Intel NPU/iGPU). Выбор бэкенда авто по device.py или config.INFERENCE_DEVICE.
Заменяет старое core/inference.py (llama-cpp выпилен)."""
from __future__ import annotations
import threading
from typing import Iterator

import config

_ACTIVE_FILE = config.DATA_DIR / "active_model.txt"


def _remember(model_id: str) -> None:
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _ACTIVE_FILE.write_text(model_id, encoding="utf-8")
    except Exception:
        pass


def last_model() -> str:
    if _ACTIVE_FILE.exists():
        mid = _ACTIVE_FILE.read_text(encoding="utf-8").strip()
        if mid in config.MODEL_REGISTRY:
            return mid
    return config.DEFAULT_MODEL_ID


class Engine:
    """Активная модель + горячее переключение бэкенда/модели."""

    def __init__(self) -> None:
        self.impl = None
        self.adapter = None
        self._lock = threading.Lock()

    @property
    def model_id(self):
        return self.impl.model_id if self.impl else None

    @property
    def loaded(self) -> bool:
        return bool(self.impl and self.impl.loaded)

    @property
    def backend(self):
        return self.impl.backend if self.impl else None

    def backend_for(self, model_id: str) -> str:
        spec = config.MODEL_REGISTRY[model_id]
        pref = config.INFERENCE_DEVICE
        if pref and pref != "auto":
            best = pref
        else:
            try:
                from core import device
                best = device.best_backend()
            except Exception:
                best = "cpu"
        # OV IR только если есть ov_repo и выбран openvino-бэкенд
        if best == "openvino" and spec.get("type") == "ov" and spec.get("ov_repo"):
            return "openvino"
        if best == "openvino":
            return "cpu"  # нет OV-варианта → torch на CPU из safetensors
        return best  # cuda | rocm | mps | cpu

    def load(self, model_id: str, adapter: str | None = None) -> None:
        be = self.backend_for(model_id)
        with self._lock:
            if be == "openvino":
                from core.engine.engine_openvino import OVEngine
                impl = OVEngine()
            else:
                from core.engine.engine_torch import TorchEngine
                impl = TorchEngine(device_backend=be)
            impl.load(model_id)
            self.impl = impl
            self.adapter = None
            if adapter:
                impl.load_adapter(adapter)
                self.adapter = adapter
        _remember(model_id)

    def attach_adapter(self, path: str) -> None:
        if not self.impl:
            raise RuntimeError("Сначала загрузите модель")
        with self._lock:
            self.impl.load_adapter(path)
            self.adapter = path

    def detach_adapter(self) -> None:
        mid = self.model_id
        self.adapter = None
        if mid:
            self.load(mid)  # перезагрузка базовой модели без адаптера

    def generate_stream(self, messages: list[dict], **kw) -> Iterator[str]:
        if not self.loaded:
            raise RuntimeError("Модель не загружена")
        yield from self.impl.generate_stream(messages, **kw)

    def request_stop(self) -> None:
        if self.impl:
            self.impl.request_stop()

    def unload(self) -> None:
        with self._lock:
            if self.impl:
                self.impl.unload()
            self.impl = None


engine = Engine()


def autoload() -> None:
    """Загрузить последнюю/дефолтную модель при старте, если скачана."""
    if not config.INFERENCE.get("auto_load"):
        return
    from core import model_registry
    mid = last_model()
    if model_registry.is_downloaded(mid):
        try:
            engine.load(mid)
        except Exception:
            pass
