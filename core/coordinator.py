"""Координатор: маршрутизация запроса к нужному агенту и автономный цикл.
Шаг 1 — прямой проход в модель (базовый чат). Маршрутизация/цикл — шаг 4."""
from __future__ import annotations
from typing import Iterator

from core.inference import engine

SYSTEM_PROMPT = (
    "Ты — локальный автономный ассистент управления ПК. "
    "Отвечай кратко и по делу на языке пользователя."
)


def chat(message: str, history: list[dict] | None = None, stream: bool = False):
    """Базовый чат на активной модели."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})
    return engine.chat(messages, stream=stream)
