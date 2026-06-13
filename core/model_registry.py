"""Реестр моделей: список, скачивание, выбор активной, добавление своих.
Смена модели — первоклассная фича (горячая перезагрузка в inference).
Кастомные модели, добавленные из UI, персистятся в data/custom_models.json."""
from __future__ import annotations
import json
import re
from pathlib import Path

import config

_CUSTOM_FILE = config.DATA_DIR / "custom_models.json"


def _load_custom() -> dict:
    if _CUSTOM_FILE.exists():
        try:
            return json.loads(_CUSTOM_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_custom(data: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CUSTOM_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_custom() -> None:
    """Влить кастомные модели в реестр (при импорте модуля)."""
    for mid, spec in _load_custom().items():
        config.MODEL_REGISTRY[mid] = spec


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


def repo_files(repo: str) -> list[str]:
    """Список GGUF-файлов в репозитории HF (для выбора в UI)."""
    from huggingface_hub import list_repo_files  # lazy
    return sorted(f for f in list_repo_files(repo) if f.endswith(".gguf"))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "model"


def add_model(spec: dict) -> str:
    """Добавить свою GGUF-модель из UI. spec: name, repo, filename, [quant, size_gb, note].
    Персистится и переживает перезапуск. Возвращает id."""
    mid = spec.get("id") or _slug(spec.get("name") or spec["filename"].replace(".gguf", ""))
    base = mid
    i = 2
    while mid in config.MODEL_REGISTRY and mid not in _load_custom():
        mid = f"{base}-{i}"; i += 1
    entry = {
        "name": spec.get("name") or mid,
        "repo": spec["repo"],
        "filename": spec["filename"],
        "quant": spec.get("quant", ""),
        "size_gb": float(spec.get("size_gb") or 0),
        "trainable_local": bool(spec.get("trainable_local", False)),
        "note": spec.get("note", ""),
        "type": "gguf",
        "source": "custom",
    }
    config.MODEL_REGISTRY[mid] = entry
    custom = _load_custom(); custom[mid] = entry; _save_custom(custom)
    return mid


def remove_model(model_id: str) -> bool:
    """Удалить кастомную модель (встроенные не трогаем)."""
    custom = _load_custom()
    if model_id not in custom:
        return False
    del custom[model_id]; _save_custom(custom)
    config.MODEL_REGISTRY.pop(model_id, None)
    return True


# Влить кастомные модели при импорте
_merge_custom()
