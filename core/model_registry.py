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
    d = config.model_path(model_id)
    return d.exists() and any(d.iterdir())


def resolve_repo(model_id: str, backend: str | None = None) -> str:
    """Какой репозиторий качать под активный бэкенд.
    Intel/openvino → OV IR (ov_repo); CUDA/ROCm/MPS/CPU → safetensors (hf_repo)."""
    m = config.MODEL_REGISTRY[model_id]
    if backend == "openvino" and m.get("ov_repo"):
        return m["ov_repo"]
    return m.get("hf_repo") or m.get("repo") or m.get("ov_repo")


def ensure_model(model_id: str, backend: str | None = None) -> Path:
    """Качает модель-директорию (snapshot), если ещё нет. Возвращает путь к папке."""
    if model_id not in config.MODEL_REGISTRY:
        raise KeyError(f"Неизвестная модель: {model_id}")
    dst = config.model_path(model_id)
    if is_downloaded(model_id):
        return dst

    if backend is None:
        try:
            from core import device
            backend = device.best_backend()
        except Exception:
            backend = "cpu"
    repo = resolve_repo(model_id, backend)
    if not repo:
        if config.MODEL_REGISTRY.get(model_id, {}).get("type") == "scratch":
            raise ValueError("Модель «с нуля» ещё не обучена — обучите её в панели «Обучение» (режим «С нуля»), потом загружайте")
        raise ValueError(f"Нет источника для модели {model_id}")

    from huggingface_hub import snapshot_download  # lazy
    m = config.MODEL_REGISTRY[model_id]
    dst.mkdir(parents=True, exist_ok=True)
    print(f"Качаю {m['name']} [{repo}] (~{m.get('size_gb', '?')} ГБ)...", flush=True)
    snapshot_download(repo_id=repo, local_dir=str(dst))
    return dst


def repo_files(repo: str) -> list[str]:
    """Список GGUF-файлов в репозитории HF (для выбора в UI)."""
    from huggingface_hub import list_repo_files  # lazy
    return sorted(f for f in list_repo_files(repo) if f.endswith(".gguf"))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "model"


def add_model(spec: dict) -> str:
    """Добавить свою GGUF-модель из UI. spec: name, repo, filename, [quant, size_gb, note].
    Персистится и переживает перезапуск. Возвращает id."""
    mid = spec.get("id") or _slug(spec.get("name") or (spec.get("filename") or "").replace(".gguf", ""))
    base = mid
    i = 2
    while mid in config.MODEL_REGISTRY and mid not in _load_custom():
        mid = f"{base}-{i}"; i += 1
    entry = dict(spec)
    entry["name"] = spec.get("name") or mid
    entry.setdefault("type", "hf")
    entry["size_gb"] = float(spec.get("size_gb") or 0)
    entry["note"] = spec.get("note", "")
    entry["source"] = "custom"
    entry.pop("id", None)
    if "arch" in entry:
        arch = entry["arch"]
        n_embd = int(arch.get("n_embd", 0))
        n_heads = int(arch.get("n_heads", 1))
        if n_embd > 0 and n_embd % n_heads != 0:
            raise ValueError(f"Размерность {n_embd} не кратна числу голов {n_heads}. "
                             f"Укажите n_embd, кратный n_heads (например, n_heads={n_embd // (n_embd // n_heads)}).")
    config.MODEL_REGISTRY[mid] = entry
    custom = _load_custom(); custom[mid] = entry; _save_custom(custom)
    return mid


def update_model(model_id: str, updates: dict) -> bool:
    """Обновить метаданные модели (name, note, quant, size_gb, trainable)."""
    if model_id not in config.MODEL_REGISTRY:
        return False
    entry = config.MODEL_REGISTRY[model_id]
    for key in ("name", "note", "quant", "size_gb", "trainable"):
        if key in updates:
            entry[key] = updates[key]
    custom = _load_custom()
    if model_id in custom:
        for key in ("name", "note", "quant", "size_gb", "trainable"):
            if key in updates:
                custom[model_id][key] = updates[key]
        _save_custom(custom)
    return True


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
