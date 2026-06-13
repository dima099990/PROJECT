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
# Смена модели — первоклассная фича. Добавляй сюда или через UI.
# filename — имя GGUF в репозитории HF (квант Q4_K_M / IQ4_XS).
MODEL_REGISTRY: dict[str, dict] = {
    "deepseek-1.5b": {
        "name": "DeepSeek-R1-Distill-Qwen-1.5B",
        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF",
        "filename": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        "quant": "Q4_K_M",
        "size_gb": 1.1,
        "trainable_local": True,   # дообучается на ноуте
        "note": "Лёгкая, для тестов и локального дообучения",
    },
    "deepseek-7b": {
        "name": "DeepSeek-R1-Distill-Qwen-7B",
        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        "filename": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
        "quant": "Q4_K_M",
        "size_gb": 4.7,
        "trainable_local": False,
        "note": "Дефолт под 16 ГБ RAM",
    },
    "deepseek-14b": {
        "name": "DeepSeek-R1-Distill-Qwen-14B",
        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF",
        "filename": "DeepSeek-R1-Distill-Qwen-14B-Q4_K_M.gguf",
        "quant": "Q4_K_M",
        "size_gb": 9.0,
        "trainable_local": False,
        "note": "Медленно на ноуте, для сервера",
    },
}
DEFAULT_MODEL_ID = os.getenv("AI_DEFAULT_MODEL", "deepseek-7b")

def model_path(model_id: str) -> Path:
    return MODELS_DIR / MODEL_REGISTRY[model_id]["filename"]

# --- Инференс (llama-cpp) ---
INFERENCE = {
    "n_ctx": int(os.getenv("AI_N_CTX", "4096")),
    "n_threads": int(os.getenv("AI_N_THREADS", str(os.cpu_count() or 4))),
    "n_gpu_layers": int(os.getenv("AI_N_GPU_LAYERS", "0")),  # 0 = CPU-only
    "temperature": 0.6,
    "top_p": 0.9,
    "repeat_penalty": 1.1,
    "max_tokens": 1024,
    "auto_load": True,   # грузить активную/дефолтную модель при старте сервера
}

# Бэкенд инференса: auto = выбрать лучший по железу (cuda>rocm>mps>openvino>cpu)
INFERENCE_DEVICE = os.getenv("AI_DEVICE", "auto")  # auto|cuda|rocm|mps|openvino|cpu

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
    # Белый список рабочих папок. Вне их — только чтение. Меняется в UI.
    "work_dirs": [str(ROOT)],
    "require_confirm": False,   # автономно без подтверждений
    "use_trash": True,         # удаление = перенос в TRASH_DIR
    "stop_flag": False,        # стоп-кнопка из UI
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
    "self_modify": False, # включается осознанно
}

# --- Режим развёртывания ---
DEPLOY_MODE = os.getenv("AI_MODE", "LOCAL")  # LOCAL | REMOTE (задел)
