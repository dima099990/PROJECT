"""Реестр LoRA-адаптеров: сохранение, список, подключение/отключение к базовой
модели, переключение в UI. Шаг 1 — список с диска. Подключение на шаге 6."""
from __future__ import annotations
import config

active_adapter: str | None = None


def list_adapters() -> list[dict]:
    config.ADAPTERS_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in config.ADAPTERS_DIR.iterdir():
        if p.is_dir():
            out.append({"id": p.name, "path": str(p), "active": p.name == active_adapter})
    return out


def attach(adapter_id: str) -> dict:
    return {"ok": False, "reason": "not_implemented"}  # шаг 6


def detach() -> dict:
    global active_adapter
    active_adapter = None
    return {"ok": True}
