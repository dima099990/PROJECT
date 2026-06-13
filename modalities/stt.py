"""Speech-to-Text (заглушка). Реализация подключается без правки ядра."""
from __future__ import annotations


def transcribe(audio_path: str) -> dict:
    return {"ok": False, "reason": "stt disabled"}
