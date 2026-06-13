"""Text-to-Speech (заглушка). Реализация подключается без правки ядра."""
from __future__ import annotations


def synthesize(text: str) -> dict:
    return {"ok": False, "reason": "tts disabled"}
