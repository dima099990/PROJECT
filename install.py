"""Установка одной командой (кроссплатформенно): python install.py
Создаёт .venv, ставит правильный PyTorch-билд + бэкенд под ЭТО железо,
остальные зависимости, качает дефолтную модель Qwen3. Нужен Python 3.10+ и интернет.
После — python run.py
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

# UTF-8 для Windows-консоли
if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass

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


def has_nvidia() -> bool:
    if not shutil.which("nvidia-smi"):
        return False
    try:
        subprocess.check_output(["nvidia-smi"], stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def has_rocm() -> bool:
    return sys.platform.startswith("linux") and bool(shutil.which("rocminfo"))


def main() -> None:
    if sys.version_info < (3, 10):
        sys.exit("Нужен Python 3.10+")

    step("1/5 Создаю .venv")
    if not VENV.exists():
        venv.EnvBuilder(with_pip=True).create(VENV)
    py = str(venv_python())
    run([py, "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"])

    step("2/5 PyTorch под железо")
    if has_nvidia():
        # torch 2.4.1 cu121: поддерживает старые GPU (Pascal sm_61, напр. GTX 1060)
        # И имеет новый is_autocast_enabled(device_type) — совместим с transformers 5.x.
        # Не ставить cu118/torch<2.4 — упадёт "is_autocast_enabled() takes no arguments".
        print("NVIDIA обнаружена → torch 2.4.1 cu121 (Pascal+совместимость)")
        run([py, "-m", "pip", "install", "torch==2.4.1", "--index-url", "https://download.pytorch.org/whl/cu121"])
    elif has_rocm():
        print("AMD ROCm обнаружена → ROCm-сборка torch")
        run([py, "-m", "pip", "install", "torch", "--index-url", "https://download.pytorch.org/whl/rocm6.0"])
    else:
        print("Без дискретной NVIDIA/AMD → стандартная сборка torch (CPU/MPS/Intel)")
        run([py, "-m", "pip", "install", "torch"])

    step("3/5 Зависимости (requirements.txt)")
    run([py, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])

    step("4/5 Бэкенд-экстра под железо")
    if has_nvidia():
        try:
            run([py, "-m", "pip", "install", "bitsandbytes"])  # 4-bit на CUDA
        except Exception:
            print("bitsandbytes не встал (не критично)")

    step("5/5 Детект железа + дефолтная модель")
    run([py, "-c",
         "from core import device; import json; print('DEVICE:', json.dumps(device.detect(), ensure_ascii=False)); "
         "import config; from core.model_registry import ensure_model; "
         "ensure_model(config.DEFAULT_MODEL_ID)"])

    print("\nГотово. Запуск:  python run.py")


if __name__ == "__main__":
    main()
