"""Координатор: формирование контекста и потоковая генерация на активной модели.
Маршрутизация по агентам и автономный цикл — Этап 5."""
from __future__ import annotations
from typing import Iterator

from core.engine import engine

SYSTEM_PROMPT = (
    "Ты — Local AI, локальный ассистент управления ПК. "
    "Отвечай ясно, связно и грамотно ТОЛЬКО на языке пользователя "
    "(по умолчанию русский). Не смешивай языки, не выдумывай несуществующие "
    "термины. Если чего-то не знаешь — честно скажи. Форматируй ответ в Markdown."
)


def _build(message: str, history: list[dict] | None) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    messages.append({"role": "user", "content": message})
    return messages


def chat_stream(message: str, history: list[dict] | None = None) -> Iterator[str]:
    """Генератор токенов для потокового вывода."""
    yield from engine.generate_stream(_build(message, history))
