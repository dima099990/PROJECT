"""Инструменты агентов: файлы (полный диск), shell, exec_python, web.
Страховки: запись/удаление через safety (whitelist опц.), удаление=корзина,
лог всех операций, стоп-флаг, таймауты. Кроссплатформенно (pathlib)."""
from __future__ import annotations
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import config
from core import safety

_MAX_READ = 2_000_000  # 2 МБ на чтение в контекст


def _p(path: str | Path) -> Path:
    """Нормализация путей (терпимость к огрехам модели):
    /C:/PROJECT, \\C:\\PROJECT -> C:/PROJECT; убираем кавычки; ~ разворачиваем."""
    s = str(path).strip().strip('"').strip("'")
    # ведущий слэш перед буквой диска (Windows): /C:/.. или \C:\.. -> C:/..
    m = re.match(r"^[\\/]+([a-zA-Z]:[\\/].*)$", s)
    if m:
        s = m.group(1)
    return Path(s).expanduser()


def _err(tool, msg, **extra):
    return {"tool": tool, "ok": False, "error": msg, **extra}


# ---------- Файлы ----------
def fs_list(path: str = ".") -> dict:
    p = _p(path)
    if not p.exists():
        return _err("fs_list", "не найдено", path=str(p))
    if p.is_file():
        return {"tool": "fs_list", "ok": True, "path": str(p), "items": [{"name": p.name, "dir": False, "size": p.stat().st_size}]}
    items = []
    for c in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try:
            items.append({"name": c.name, "dir": c.is_dir(), "size": c.stat().st_size if c.is_file() else 0})
        except Exception:
            pass
    return {"tool": "fs_list", "ok": True, "path": str(p.resolve()), "writable": safety.is_writable(p), "items": items}


def fs_read(path: str, max_bytes: int = _MAX_READ) -> dict:
    p = _p(path)
    if not p.is_file():
        return _err("fs_read", "не файл", path=str(p))
    try:
        data = p.read_text(encoding="utf-8", errors="replace")[:max_bytes]
        return {"tool": "fs_read", "ok": True, "path": str(p), "chars": len(data), "content": data}
    except Exception as e:
        return _err("fs_read", str(e), path=str(p))


def fs_write(path: str, content: str) -> dict:
    p = _p(path)
    if not safety.is_writable(p):
        return _err("fs_write", "запрещено whitelist'ом", path=str(p))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        safety.log_action("fs_write", {"path": str(p), "chars": len(content)})
        return {"tool": "fs_write", "ok": True, "path": str(p)}
    except Exception as e:
        return _err("fs_write", str(e), path=str(p))


def fs_edit(path: str, old: str, new: str) -> dict:
    p = _p(path)
    if not safety.is_writable(p):
        return _err("fs_edit", "запрещено whitelist'ом", path=str(p))
    if not p.is_file():
        return _err("fs_edit", "не файл", path=str(p))
    try:
        text = p.read_text(encoding="utf-8")
        if old not in text:
            return _err("fs_edit", "old не найден", path=str(p))
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
        safety.log_action("fs_edit", {"path": str(p)})
        return {"tool": "fs_edit", "ok": True, "path": str(p)}
    except Exception as e:
        return _err("fs_edit", str(e), path=str(p))


def fs_move(src: str, dst: str) -> dict:
    s, d = _p(src), _p(dst)
    if not safety.is_writable(d):
        return _err("fs_move", "запрещено whitelist'ом", dst=str(d))
    try:
        import shutil
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        safety.log_action("fs_move", {"src": str(s), "dst": str(d)})
        return {"tool": "fs_move", "ok": True, "src": str(s), "dst": str(d)}
    except Exception as e:
        return _err("fs_move", str(e))


def fs_delete(path: str) -> dict:
    p = _p(path)
    if not safety.is_writable(p):
        return _err("fs_delete", "запрещено whitelist'ом", path=str(p))
    try:
        dst = safety.to_trash(p)  # удаление = корзина проекта
        return {"tool": "fs_delete", "ok": True, "trashed_to": str(dst)}
    except Exception as e:
        return _err("fs_delete", str(e), path=str(p))


def fs_mkdir(path: str) -> dict:
    p = _p(path)
    if not safety.is_writable(p):
        return _err("fs_mkdir", "запрещено whitelist'ом", path=str(p))
    try:
        p.mkdir(parents=True, exist_ok=True)
        safety.log_action("fs_mkdir", {"path": str(p)})
        return {"tool": "fs_mkdir", "ok": True, "path": str(p)}
    except Exception as e:
        return _err("fs_mkdir", str(e))


# ---------- Терминал ----------
def shell(command: str, cwd: str | None = None, timeout: int | None = None) -> dict:
    if safety.stop_requested():
        return _err("shell", "остановлено стоп-флагом")
    timeout = timeout or config.SAFETY.get("shell_timeout", 60)
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        cmd = ["bash", "-lc", command]
    safety.log_action("shell", {"cmd": command[:200], "cwd": cwd})
    try:
        r = subprocess.run(cmd, cwd=cwd or str(config.ROOT), capture_output=True,
                           text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return {"tool": "shell", "ok": r.returncode == 0, "code": r.returncode,
                "stdout": (r.stdout or "")[-20000:], "stderr": (r.stderr or "")[-20000:]}
    except subprocess.TimeoutExpired:
        return _err("shell", f"таймаут {timeout}с")
    except Exception as e:
        return _err("shell", str(e))


def exec_python(code: str, timeout: int = 60) -> dict:
    if safety.stop_requested():
        return _err("exec_python", "остановлено стоп-флагом")
    safety.log_action("exec_python", {"chars": len(code)})
    tmp = Path(tempfile.gettempdir()) / f"_exec_{os.getpid()}.py"
    try:
        tmp.write_text(code, encoding="utf-8")
        env = {**os.environ, "PYTHONUTF8": "1"}
        r = subprocess.run([sys.executable, str(tmp)], capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace", env=env)
        return {"tool": "exec_python", "ok": r.returncode == 0, "code": r.returncode,
                "stdout": (r.stdout or "")[-20000:], "stderr": (r.stderr or "")[-20000:]}
    except subprocess.TimeoutExpired:
        return _err("exec_python", f"таймаут {timeout}с")
    except Exception as e:
        return _err("exec_python", str(e))
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass


# ---------- Веб ----------
def web_search(query: str, max_results: int = 8) -> dict:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            res = list(ddgs.text(query, max_results=max_results))
        safety.log_action("web_search", {"q": query, "n": len(res)})
        return {"tool": "web_search", "ok": True, "results":
                [{"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")} for r in res]}
    except Exception as e:
        return _err("web_search", str(e))


def web_fetch(url: str) -> dict:
    from core import parser
    r = parser.fetch_url(url)
    return {"tool": "web_fetch", **r}


REGISTRY = {
    "fs_list": fs_list, "fs_read": fs_read, "fs_write": fs_write, "fs_edit": fs_edit,
    "fs_move": fs_move, "fs_delete": fs_delete, "fs_mkdir": fs_mkdir,
    "shell": shell, "exec_python": exec_python,
    "web_search": web_search, "web_fetch": web_fetch,
}
