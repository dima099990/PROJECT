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

    def unload(self) -> None:
        with self._lock:
            self._llm = None
            self._model_id = None

    def chat(self, messages: list[dict], stream: bool = False, **kw):
        if self._llm is None:
            raise RuntimeError("Модель не загружена")
        params = {
            "temperature": config.INFERENCE["temperature"],
            "max_tokens": config.INFERENCE["max_tokens"],
            **kw,
        }
        return self._llm.create_chat_completion(messages=messages, stream=stream, **params)


# Глобальный движок
engine = Engine()
