"""Самопереписывание (задел). Безопасный контур: git-commit до изменения,
отдельная ветка, проверка синтаксиса, авто-откат к рабочему коммиту.
Шаг 1 — каркас. Включается флагом FEATURES['self_modify'] (шаг 7)."""
from __future__ import annotations
import ast
import subprocess
from pathlib import Path

import config


def syntax_ok(path: str | Path) -> bool:
    try:
        ast.parse(Path(path).read_text(encoding="utf-8"))
        return True
    except SyntaxError:
        return False


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=config.ROOT, capture_output=True,
                          text=True).stdout.strip()


def safe_edit(path: str, new_code: str, branch: str = "self-mod") -> dict:
    """Каркас: ветка -> запись -> проверка синтаксиса -> commit / откат."""
    if not config.FEATURES.get("self_modify"):
        return {"ok": False, "reason": "self_modify disabled"}
    # шаг 7: полная реализация
    return {"ok": False, "reason": "not_implemented"}
