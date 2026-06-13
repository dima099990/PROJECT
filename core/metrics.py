"""Метрики загрузки системы (psutil) — кроссплатформенно (ПК/сервер).
Работает одинаково на Windows/Linux. Используется графиками в UI и /ws/status."""
from __future__ import annotations

import config

_psutil = None
_device_cache = None


def device_info() -> dict:
    """Детект железа/бэкенда (кеш — детект дорогой)."""
    global _device_cache
    if _device_cache is None:
        try:
            from core import device
            _device_cache = device.detect()
        except Exception as e:
            _device_cache = {"error": str(e)}
    return _device_cache


def _p():
    global _psutil
    if _psutil is None:
        import psutil  # lazy
        _psutil = psutil
        _psutil.cpu_percent(interval=None)  # инициализация базлайна
    return _psutil


def snapshot() -> dict:
    try:
        ps = _p()
        vm = ps.virtual_memory()
        anchor = str(config.ROOT.anchor) or "/"
        disk = ps.disk_usage(anchor)
        return {
            "cpu": ps.cpu_percent(interval=None),
            "ram": vm.percent,
            "ram_used_mb": round(vm.used / 1048576),
            "ram_total_mb": round(vm.total / 1048576),
            "disk": disk.percent,
            "disk_used_gb": round(disk.used / 1073741824, 1),
            "disk_total_gb": round(disk.total / 1073741824, 1),
            "cores": ps.cpu_count(logical=True),
            "device": device_info(),
        }
    except Exception as e:
        return {"error": str(e)}
