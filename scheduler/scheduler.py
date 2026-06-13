"""Планировщик задач (APScheduler) — задел, по умолчанию выключен
(FEATURES['scheduler']=False). Запуск по расписанию/триггерам. Шаг 8."""
from __future__ import annotations
import config

_scheduler = None


def start() -> bool:
    global _scheduler
    if not config.FEATURES.get("scheduler"):
        return False
    from apscheduler.schedulers.background import BackgroundScheduler  # lazy
    _scheduler = BackgroundScheduler()
    _scheduler.start()
    return True


def jobs() -> list[dict]:
    return []  # шаг 8
