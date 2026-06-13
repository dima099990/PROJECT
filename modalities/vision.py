"""Vision / анализ изображений (заглушка). Подключается без правки ядра."""
from __future__ import annotations


def describe(image_path: str) -> dict:
    return {"ok": False, "reason": "vision disabled"}
