"""Старт сервера одной командой: python run.py
Поднимает FastAPI (uvicorn). Открой http://127.0.0.1:8000
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
IS_WIN = os.name == "nt"


def venv_python() -> Path:
    return VENV / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")


def main() -> None:
    # Если запущены системным python — перезапускаемся из venv.
    py = venv_python()
    if py.exists() and Path(sys.executable).resolve() != py.resolve():
        os.execv(str(py), [str(py), __file__, *sys.argv[1:]])

    import uvicorn
    import config
    uvicorn.run("web.api.app:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
