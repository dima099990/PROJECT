"""Обёртка над llama-cpp-python (GGUF). Синглтон активной модели + горячая
перезагрузка. llama_cpp импортируется лениво, чтобы сервер поднимался без модели."""
from __future__ import annotations
import threading
from typing import Iterator, Optional

import config
from core import model_registry


class Engine:
    def __init__(self) -> None:
        self._llm = None
        self._model_id: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def model_id(self) -> Optional[str]:
        return self._model_id

    @property
    def loaded(self) -> bool:
        return self._llm is not None

    def load(self, model_id: str) -> None:
        """Загрузить/переключить модель (горячая перезагрузка)."""
        from llama_cpp import Llama  # lazy
        path = model_registry.ensure_model(model_id)
        with self._lock:
            self._llm = Llama(
                model_path=str(path),
                n_ctx=config.INFERENCE["n_ctx"],
                n_threads=config.INFERENCE["n_threads"],
                n_gpu_layers=config.INFERENCE["n_gpu_layers"],
                verbose=False,
            )
            self._model_id = model_id
        _remember(model_id)

    def unload(self) -> None:
        with self._lock:
            self._llm = None
            self._model_id = None

    def chat(self, messages: list[dict], stream: bool = False, **kw):
        if self._llm is None:
            raise RuntimeError("Модель не загружена")
        params = {
            "temperature": config.INFERENCE["temperature"],
            "top_p": config.INFERENCE.get("top_p", 0.9),
            "repeat_penalty": config.INFERENCE.get("repeat_penalty", 1.1),
            "max_tokens": config.INFERENCE["max_tokens"],
            **kw,
        }
        return self._llm.create_chat_completion(messages=messages, stream=stream, **params)


# Глобальный движок
engine = Engine()

# --- Запоминание активной модели + авто-загрузка при старте ---
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


def autoload() -> None:
    """Загрузить последнюю/дефолтную модель, если она скачана (для startup)."""
    if not config.INFERENCE.get("auto_load"):
        return
    mid = last_model()
    if model_registry.is_downloaded(mid):
        try:
            engine.load(mid)
        except Exception:
            pass
