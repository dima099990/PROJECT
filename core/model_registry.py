"""Реестр моделей: список, скачивание, выбор активной.
Смена модели — первоклассная фича (горячая перезагрузка в inference)."""
from __future__ import annotations
from pathlib import Path

import config


def list_models() -> list[dict]:
    out = []
    for mid, m in config.MODEL_REGISTRY.items():
        out.append({
            "id": mid,
            **m,
            "downloaded": config.model_path(mid).exists(),
            "is_default": mid == config.DEFAULT_MODEL_ID,
        })
    return out


def is_downloaded(model_id: str) -> bool:
    return config.model_path(model_id).exists()


def ensure_model(model_id: str) -> Path:
    """Качает GGUF, если ещё нет. Возвращает путь к файлу."""
    if model_id not in config.MODEL_REGISTRY:
        raise KeyError(f"Неизвестная модель: {model_id}")
    dst = config.model_path(model_id)
    if dst.exists():
        return dst

    from huggingface_hub import hf_hub_download  # lazy
    m = config.MODEL_REGISTRY[model_id]
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Качаю {m['name']} ({m['size_gb']} ГБ)...", flush=True)
    path = hf_hub_download(
        repo_id=m["repo"],
        filename=m["filename"],
        local_dir=str(config.MODELS_DIR),
    )
    return Path(path)


def register_model(model_id: str, spec: dict) -> None:
    """Добавить модель в реестр в рантайме (из UI). spec: name,repo,filename,quant,size_gb."""
    config.MODEL_REGISTRY[model_id] = spec
