"""Страховки автономной работы: белый список папок, корзина, лог действий,
стоп-флаг. Реальная логика операций — в tools.py (шаг 4)."""
from __future__ import annotations
import json
import shutil
import time
from pathlib import Path

import config

_ACTION_LOG = config.LOGS_DIR / "actions.jsonl"


def stop_requested() -> bool:
    return bool(config.SAFETY.get("stop_flag"))


def set_stop(value: bool) -> None:
    config.SAFETY["stop_flag"] = value


def work_dirs() -> list[Path]:
    return [Path(p).resolve() for p in config.SAFETY["work_dirs"]]


def is_writable(path: str | Path) -> bool:
    """Полный доступ по умолчанию. Если включён whitelist — только внутри work_dirs."""
    if not config.SAFETY.get("whitelist_enabled"):
        return True
    p = Path(path).resolve()
    return any(p == wd or wd in p.parents for wd in work_dirs())


def git_snapshot(message: str = "auto-snapshot") -> dict:
    """Коммит-снапшот проекта перед массовыми правками (защита/откат)."""
    import subprocess
    try:
        subprocess.run(["git", "add", "-A"], cwd=config.ROOT, capture_output=True)
        r = subprocess.run(["git", "commit", "-m", message], cwd=config.ROOT,
                           capture_output=True, text=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.ROOT,
                             capture_output=True, text=True).stdout.strip()
        log_action("git_snapshot", {"sha": sha[:8], "message": message})
        return {"ok": True, "sha": sha}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def log_action(action: str, detail: dict) -> None:
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action, **detail}
    with _ACTION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def to_trash(path: str | Path) -> Path:
    """Удаление = перенос в корзину проекта."""
    src = Path(path).resolve()
    config.TRASH_DIR.mkdir(parents=True, exist_ok=True)
    dst = config.TRASH_DIR / f"{int(time.time())}_{src.name}"
    shutil.move(str(src), str(dst))
    log_action("trash", {"src": str(src), "dst": str(dst)})
    return dst
