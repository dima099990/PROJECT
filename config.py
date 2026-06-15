"""Центральная конфигурация. Всё настраиваемое — здесь или в .env."""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Windows-консоль по умолчанию cp1252 — кириллица в print() падает. Форсируем UTF-8.
if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass

ROOT = Path(__file__).resolve().parent

# --- Пути ---
MODELS_DIR = ROOT / "models"
MODELS_OV_DIR = MODELS_DIR / "ov"      # OpenVINO IR (Intel)
MODELS_HF_DIR = MODELS_DIR / "hf"      # safetensors (CUDA/прочее + обучение)
MODELS_CUSTOM_DIR = MODELS_DIR / "custom"
DATA_DIR = ROOT / "data"
ADAPTERS_DIR = DATA_DIR / "adapters"
CHROMA_DIR = DATA_DIR / "chroma"
TRASH_DIR = DATA_DIR / "trash"          # "корзина проекта" для удалений
LOGS_DIR = ROOT / "logs"

# --- Сервер ---
HOST = os.getenv("AI_HOST", "127.0.0.1")
PORT = int(os.getenv("AI_PORT", "8000"))

# --- Авторизация ---
# Пароль берётся из .env (AI_PASSWORD). Дефолт только для первого запуска.
PASSWORD = os.getenv("AI_PASSWORD", "admin")
SECRET_KEY = os.getenv("AI_SECRET", "change-me-in-env")

# --- Язык интерфейса по умолчанию ---
DEFAULT_LANG = os.getenv("AI_LANG", "ru")  # ru | en

# --- Реестр моделей -------------------------------------------------------
# Qwen3 (dense, Apache-2.0, русский+код, дообучаемые). Модель = директория.
#   type: ov  -> инференс из OpenVINO IR (Intel NPU/iGPU)
#         hf  -> инференс из safetensors (CUDA/ROCm/MPS/CPU)
#   ov_repo  -> готовый OV IR на HF (для Intel)
#   hf_repo  -> оригинальные safetensors (обучение + инференс на CUDA/прочем)
# Реестр сам выбирает формат под активный бэкенд (см. model_registry.resolve).
MODEL_REGISTRY: dict[str, dict] = {
    "qwen3-0.6b": {
        "name": "Qwen3-0.6B",
        "type": "hf",
        "ov_repo": "",
        "hf_repo": "Qwen/Qwen3-0.6B",
        "quant": "fp16",
        "size_gb": 1.5,
        "trainable": True,
        "note": "Очень лёгкая — для слабого железа (CPU/16 ГБ), работает сразу",
    },
    "qwen3-8b": {
        "name": "Qwen3-8B",
        "type": "ov",
        "ov_repo": "OpenVINO/Qwen3-8B-int4-ov",
        "hf_repo": "Qwen/Qwen3-8B",
        "quant": "int4",
        "size_gb": 5.0,
        "trainable": True,
        "note": "Дефолт: ноут (Intel NPU/iGPU INT4) и сервер",
    },
    "qwen3-14b": {
        "name": "Qwen3-14B",
        "type": "ov",
        "ov_repo": "OpenVINO/Qwen3-14B-int4-ov",
        "hf_repo": "Qwen/Qwen3-14B",
        "quant": "int4",
        "size_gb": 9.0,
        "trainable": True,
        "note": "Средняя: мощный ПК / аренда GPU",
    },
    "qwen3-coder-30b": {
        "name": "Qwen3-Coder-30B",
        "type": "hf",
        "ov_repo": "",
        "hf_repo": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
        "quant": "fp16",
        "size_gb": 60.0,
        "trainable": True,
        "note": "Код/тяжёлая: аренда GPU",
    },
}
DEFAULT_MODEL_ID = os.getenv("AI_DEFAULT_MODEL", "qwen3-0.6b")  # лёгкая по умолчанию (ноут)
ACTIVE_MODEL_FILE = DATA_DIR / "active_model.txt"


def save_active_model(model_id: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_MODEL_FILE.write_text(model_id.strip(), encoding="utf-8")


def load_active_model() -> str | None:
    if ACTIVE_MODEL_FILE.exists():
        try:
            mid = ACTIVE_MODEL_FILE.read_text(encoding="utf-8").strip()
            if mid in MODEL_REGISTRY:
                return mid
        except Exception:
            pass
    return None


def model_dir(model_id: str) -> Path:
    """Директория модели на диске (зависит от типа)."""
    spec = MODEL_REGISTRY[model_id]
    sub = {"ov": MODELS_OV_DIR, "hf": MODELS_HF_DIR}.get(spec.get("type"), MODELS_CUSTOM_DIR)
    return sub / model_id


# Обратная совместимость: model_path = директория модели.
def model_path(model_id: str) -> Path:
    return model_dir(model_id)

# --- Инференс ---
INFERENCE = {
    "n_ctx": int(os.getenv("AI_N_CTX", "8192")),
    "n_threads": int(os.getenv("AI_N_THREADS", str(os.cpu_count() or 4))),
    "temperature": 0.6,
    "top_p": 0.9,
    "repeat_penalty": 1.1,
    "max_tokens": 1024,
    "thinking": False,   # Qwen3 thinking-режим (выкл — прямые ответы, лучше для мелких)
    "auto_load": True,   # грузить активную/дефолтную модель при старте сервера
}

# Бэкенд инференса: auto = выбрать лучший по железу (cuda>rocm>mps>openvino>cpu)
INFERENCE_DEVICE = os.getenv("AI_DEVICE", "auto")  # auto|cuda|rocm|mps|openvino|cpu

# --- Переопределения настроек генерации (переживают перезапуск) ---
_SETTINGS_FILE = DATA_DIR / "settings.json"
_SETTINGS_KEYS = ("max_tokens", "temperature", "n_ctx")


def _load_settings_overrides() -> None:
    try:
        import json
        if _SETTINGS_FILE.exists():
            ov = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            for k in _SETTINGS_KEYS:
                if k in ov:
                    INFERENCE[k] = ov[k]
    except Exception:
        pass


def save_settings() -> None:
    try:
        import json
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(
            json.dumps({k: INFERENCE[k] for k in _SETTINGS_KEYS}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


_load_settings_overrides()

# --- Реестр агентов (расширяемый) ---
AGENT_REGISTRY: dict[str, dict] = {
    "coordinator": {"name": "Координатор", "role": "Маршрутизация запросов между агентами", "tools": []},
    "file":        {"name": "Файловый",    "role": "Операции с файловой системой",        "tools": ["fs_read", "fs_write", "fs_list", "fs_delete"]},
    "code":        {"name": "Кодовый",      "role": "Написание и выполнение Python",        "tools": ["python_exec"]},
    "search":      {"name": "Поисковый",    "role": "Поиск в интернете и парсинг",          "tools": ["web_search", "web_fetch"]},
    "system":      {"name": "Системный",    "role": "Выполнение shell-команд",              "tools": ["shell"]},
}

# --- Страховки автономной работы ---
SAFETY = {
    # Полный доступ к диску по умолчанию. Whitelist — опционально (вкл. в UI):
    # если whitelist_enabled, запись разрешена только внутри work_dirs.
    "whitelist_enabled": False,
    "work_dirs": [str(ROOT)],
    "require_confirm": False,   # автономно без подтверждений
    "use_trash": True,          # удаление = перенос в TRASH_DIR (защита от необратимого)
    "stop_flag": False,         # стоп-кнопка из UI
    "shell_timeout": 60,        # таймаут shell-команд, сек
}

# --- Память / RAG ---
MEMORY = {
    "embeddings_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "collection": "dialogs",
    "rag_top_k": 5,
}

# --- Фича-флаги задела ---
FEATURES = {
    "scheduler": False,   # APScheduler выключен
    "stt": False,
    "tts": False,
    "vision": False,
    "self_modify": True,  # рабочий git-safe режим самоизменения
}

# --- Режим развёртывания ---
DEPLOY_MODE = os.getenv("AI_MODE", "LOCAL")  # LOCAL | REMOTE (задел)
