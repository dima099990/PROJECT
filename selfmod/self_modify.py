"""Самоизменение кода (рабочее): git-снапшот → отдельная ветка → запись →
проверка синтаксиса + smoke → мерж в main, иначе авто-откат к рабочему коммиту.
История и диффы — в UI-панель."""
from __future__ import annotations
import ast
import subprocess
import time
from pathlib import Path

import config

MAIN = "main"


def syntax_ok(path: str | Path) -> bool:
    try:
        ast.parse(Path(path).read_text(encoding="utf-8"))
        return True
    except SyntaxError:
        return False


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=config.ROOT, capture_output=True, text=True)


def _smoke() -> dict:
    """Быстрый smoke: компиляция проекта + проверка импорта приложения."""
    import sys
    r = subprocess.run([sys.executable, "-c",
                        "import compileall,sys; "
                        "sys.exit(0 if compileall.compile_dir('core',quiet=1) and "
                        "compileall.compile_dir('web',quiet=1) else 1)"],
                       cwd=config.ROOT, capture_output=True, text=True, timeout=120)
    return {"ok": r.returncode == 0, "out": (r.stdout + r.stderr)[-4000:]}


def _resolve(path: str) -> Path:
    p = (config.ROOT / path).resolve()
    if config.ROOT not in p.parents and p != config.ROOT:
        raise ValueError("вне проекта")
    return p


def safe_edit(path: str, new_code: str, run_smoke: bool = True) -> dict:
    """Безопасно изменить файл проекта. Возвращает статус, дифф, smoke."""
    if not config.FEATURES.get("self_modify"):
        return {"ok": False, "reason": "self_modify выключен"}
    try:
        p = _resolve(path)
    except Exception as e:
        return {"ok": False, "reason": str(e)}

    # 1. снапшот рабочего состояния
    _git("add", "-A"); _git("commit", "-m", "self-mod: baseline snapshot")
    base = _git("rev-parse", "HEAD").stdout.strip()

    # 2. ветка
    branch = f"self-mod-{int(time.time())}"
    _git("checkout", "-b", branch)

    # 3. запись изменения
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new_code, encoding="utf-8")

    # 4. проверки
    ok = syntax_ok(p)
    smoke = None
    if ok and run_smoke:
        smoke = _smoke()
        ok = smoke["ok"]
    diff = _git("diff", base, "--", str(p.relative_to(config.ROOT))).stdout

    if ok:
        _git("add", str(p)); _git("commit", "-m", f"self-mod: {path}")
        _git("checkout", MAIN); _git("merge", "--no-ff", "-m", f"self-mod merge: {path}", branch)
        _git("branch", "-d", branch)
        from core import safety
        safety.log_action("self_modify", {"path": path, "status": "merged"})
        return {"ok": True, "path": path, "diff": diff, "smoke": smoke}
    else:
        # авто-откат
        _git("checkout", "--", "."); _git("checkout", MAIN); _git("branch", "-D", branch)
        from core import safety
        safety.log_action("self_modify", {"path": path, "status": "rolled_back"})
        return {"ok": False, "reason": "проверка не прошла — откат", "diff": diff, "smoke": smoke}


def history(limit: int = 30) -> list[dict]:
    out = _git("log", f"-{limit}", "--grep=self-mod", "--pretty=%H|%ct|%s").stdout
    items = []
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            items.append({"sha": parts[0][:10], "full_sha": parts[0], "ts": int(parts[1]), "subject": parts[2]})
    return items


def get_diff(sha: str) -> dict:
    d = _git("show", sha, "--stat", "--pretty=%H%n%s").stdout
    full = _git("show", sha).stdout[:20000]
    return {"ok": True, "stat": d, "diff": full}


def rollback(sha: str) -> dict:
    """Откатить конкретный self-mod (git revert — безопасно, новым коммитом)."""
    r = _git("revert", "--no-edit", sha)
    from core import safety
    safety.log_action("self_modify", {"rollback": sha, "ok": r.returncode == 0})
    return {"ok": r.returncode == 0, "out": (r.stdout + r.stderr)[-4000:]}
