"""Реестр LoRA-адаптеров: список, подключение/отключение к активной модели,
переключение в UI. Адаптер применяется поверх базовой модели в TorchEngine."""
from __future__ import annotations
import json

import config

active_adapter: str | None = None


def list_adapters() -> list[dict]:
    config.ADAPTERS_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(config.ADAPTERS_DIR.iterdir()):
        if p.is_dir() and (p / "adapter_config.json").exists():
            base = None
            try:
                base = json.loads((p / "adapter_config.json").read_text(encoding="utf-8")).get("base_model_name_or_path")
            except Exception:
                pass
            out.append({"id": p.name, "path": str(p), "base": base, "active": p.name == active_adapter})
    return out


def attach(adapter_id: str) -> dict:
    global active_adapter
    from core.engine import engine
    p = config.ADAPTERS_DIR / adapter_id
    if not (p / "adapter_config.json").exists():
        return {"ok": False, "reason": "адаптер не найден"}
    if not engine.loaded:
        return {"ok": False, "reason": "сначала загрузите модель"}
    try:
        # переподключаем от чистой базы (на случай уже подключённого адаптера)
        engine.load(engine.model_id, adapter=str(p))
        active_adapter = adapter_id
        return {"ok": True, "active": adapter_id}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def detach() -> dict:
    global active_adapter
    from core.engine import engine
    active_adapter = None
    try:
        engine.detach_adapter()
    except Exception as e:
        return {"ok": False, "reason": str(e)}
    return {"ok": True}
