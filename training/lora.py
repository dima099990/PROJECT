"""LoRA/QLoRA дообучение в отдельном процессе (не блокирует чат).
Локально реально только 1.5B-3B; для 14B — заглушка 'нужен GPU-сервер'.
Шаг 1 — статусная модель и заглушка запуска. Реализация на шаге 6."""
from __future__ import annotations
import config

# Статус обучения (отдаётся в UI по WebSocket)
status: dict = {"state": "idle", "progress": 0.0, "loss": None, "stage": "", "model_id": None}


def can_train_locally(model_id: str) -> bool:
    return bool(config.MODEL_REGISTRY.get(model_id, {}).get("trainable_local"))


def start_training(model_id: str, dataset: str = "history") -> dict:
    if not can_train_locally(model_id):
        return {"ok": False, "reason": "Нужен GPU-сервер для этой модели"}
    # шаг 6: запуск отдельного процесса peft/transformers
    status.update(state="queued", model_id=model_id, stage="подготовка")
    return {"ok": True, "status": status}
