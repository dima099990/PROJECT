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
                base = json.loads(
                    (p / "adapter_config.json").read_text(encoding="utf-8")
                ).get("base_model_name_or_path")
            except Exception:
                pass
            out.append({
                "id": p.name, "path": str(p), "base": base,
                "active": p.name == active_adapter,
            })
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
        engine.attach_adapter(str(p))
        active_adapter = adapter_id
        return {"ok": True, "active": adapter_id}
    except Exception as e:
        return {"ok": False, "reason": str(e)}

def detach() -> dict:
    global active_adapter
    from core.engine import engine
    try:
        engine.detach_adapter()
        active_adapter = None
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
