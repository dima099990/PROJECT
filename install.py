"""Запуск установки одной командой: python install.py
Создаёт venv, ставит зависимости, качает дефолтную модель.
Нужен только Python 3.10+ и интернет. После — python run.py
"""
from __future__ import annotations
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
IS_WIN = os.name == "nt"


def venv_python() -> Path:
    return VENV / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")


def step(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


def run(cmd: list[str]) -> None:
    print("$", " ".join(str(c) for c in cmd), flush=True)
    subprocess.check_call(cmd)


def main() -> None:
    if sys.version_info < (3, 10):
        sys.exit("Нужен Python 3.10+")

    step("1/4 Создаю venv")
    if not VENV.exists():
        venv.EnvBuilder(with_pip=True).create(VENV)
    py = venv_python()

    step("2/4 Обновляю pip")
    run([str(py), "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"])

    step("3/4 Ставлю зависимости (долго: llama-cpp собирается)")
    run([str(py), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])

    step("4/4 Качаю дефолтную модель")
    # Импортируем после установки зависимостей.
    run([str(py), "-c",
         "import config; from core.model_registry import ensure_model; "
         "ensure_model(config.DEFAULT_MODEL_ID)"])

    print("\nГотово. Запуск:  python run.py")


if __name__ == "__main__":
    main()
