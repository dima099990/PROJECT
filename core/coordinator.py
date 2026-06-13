"""Координатор: маршрутизация запроса к нужному агенту и автономный цикл.
Шаг 1 — прямой проход в модель (базовый чат). Маршрутизация/цикл — шаг 4."""
from __future__ import annotations
from typing import Iterator

from core.inference import engine

SYSTEM_PROMPT = (
    "Ты — Local AI, локальный ассистент управления ПК. "
    "Отвечай ясно, связно и грамотно ТОЛЬКО на языке пользователя "
    "(по умолчанию русский). Не смешивай языки, не вставляй случайные "
    "иностранные слова и не выдумывай несуществующие термины. "
    "Если чего-то не знаешь — честно скажи об этом. Форматируй ответ в Markdown."
)


def _build(message: str, history: list[dict] | None):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    messages.append({"role": "user", "content": message})
    return messages


def chat(message: str, history: list[dict] | None = None, stream: bool = False):
    """Базовый чат на активной модели (нестриминговый)."""
    return engine.chat(_build(message, history), stream=stream)


def chat_stream(message: str, history: list[dict] | None = None):
    """Генератор токенов (дельт) для потокового вывода."""
    for chunk in engine.chat(_build(message, history), stream=True):
        delta = chunk["choices"][0].get("delta", {}).get("content")
        if delta:
            yield delta
