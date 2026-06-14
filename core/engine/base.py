"""Базовый интерфейс инференс-бэкенда."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterator


class BaseEngine(ABC):
    backend = "base"

    def __init__(self) -> None:
        self.model_id = None
        self._stop = False

    @property
    def loaded(self) -> bool:
        return self.model_id is not None

    def request_stop(self) -> None:
        self._stop = True

    @abstractmethod
    def load(self, model_id: str) -> None: ...

    @abstractmethod
    def generate_stream(self, messages: list[dict], **kw) -> Iterator[str]: ...

    def unload(self) -> None:
        self.model_id = None
