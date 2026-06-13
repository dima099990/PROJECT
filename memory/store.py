"""Память диалогов + RAG на ChromaDB (локально), эмбеддинги sentence-transformers.
Шаг 1 — интерфейс. Реальное хранилище на шаге 5."""
from __future__ import annotations
import config


class MemoryStore:
    def __init__(self) -> None:
        self._client = None  # ленивый chromadb

    def add(self, role: str, text: str, meta: dict | None = None) -> None:
        ...  # шаг 5

    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        return []  # шаг 5

    def history(self, limit: int = 50) -> list[dict]:
        return []  # шаг 5


store = MemoryStore()
