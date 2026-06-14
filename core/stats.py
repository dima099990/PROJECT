"""Статистика работы: счётчики запросов, токены, время генерации (tok/s).
Персист в data/stats.json. Для панели «Статус»/«Статистика» + графики."""
from __future__ import annotations
import json
import threading
import time

import config

_FILE = config.DATA_DIR / "stats.json"
_lock = threading.Lock()


def _load() -> dict:
    if _FILE.exists():
        try:
            return json.loads(_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"total": 0, "tokens": 0, "gen_seconds": 0.0, "by_day": {}, "history": []}


def _save(d: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_FILE)


def record(tokens: int, seconds: float, model: str | None = None) -> None:
    with _lock:
        d = _load()
        day = time.strftime("%Y-%m-%d")
        d["total"] += 1
        d["tokens"] += int(tokens)
        d["gen_seconds"] += float(seconds)
        d["by_day"][day] = d["by_day"].get(day, 0) + 1
        d["history"].append({"ts": time.time(), "tokens": tokens,
                             "tok_s": round(tokens / seconds, 1) if seconds > 0 else 0,
                             "model": model})
        d["history"] = d["history"][-200:]
        _save(d)


def snapshot() -> dict:
    d = _load()
    day = time.strftime("%Y-%m-%d")
    avg_tokps = round(d["tokens"] / d["gen_seconds"], 1) if d["gen_seconds"] > 0 else 0
    return {
        "total": d["total"],
        "today": d["by_day"].get(day, 0),
        "tokens": d["tokens"],
        "avg_tok_s": avg_tokps,
        "by_day": d["by_day"],
        "history": d["history"][-60:],
    }
