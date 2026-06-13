"""Инструменты агентов: shell, python_exec, файловые операции, веб.
Шаг 1 — сигнатуры и заглушки. Реальная реализация + страховки на шаге 4."""
from __future__ import annotations

# Каждый инструмент: (name) -> callable(**kwargs) -> dict
# Заглушки возвращают NotImplemented-маркер, чтобы UI/координатор уже работали.

def _stub(name):
    def f(**kw):
        return {"tool": name, "status": "not_implemented", "args": kw}
    return f


shell = _stub("shell")
python_exec = _stub("python_exec")
fs_read = _stub("fs_read")
fs_write = _stub("fs_write")
fs_list = _stub("fs_list")
fs_delete = _stub("fs_delete")
web_search = _stub("web_search")
web_fetch = _stub("web_fetch")

REGISTRY = {
    "shell": shell, "python_exec": python_exec,
    "fs_read": fs_read, "fs_write": fs_write, "fs_list": fs_list, "fs_delete": fs_delete,
    "web_search": web_search, "web_fetch": web_fetch,
}
