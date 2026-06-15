#!/usr/bin/env python
"""CLI к локальному ИИ — чат в терминале + агент-режим с доступом к файлам/шеллу.

Запуск:
  python cli.py                      чат с активной/дефолтной моделью
  python cli.py --model qwen3-0.6b   конкретная модель
  python cli.py --agent              агент-режим (инструменты: файлы/shell/web)
  python cli.py -p "вопрос"          один ответ и выход
  python cli.py --agent -p "найди все .py в C:/PROJECT и посчитай строки"

В REPL:  /agent  /chat  /model <id>  /models  /load <id>  /clear  /help  /exit
"""
from __future__ import annotations
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass

import config  # noqa: E402


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def load_model(model_id: str) -> None:
    from core.engine import engine
    from core import model_registry
    if not model_registry.is_downloaded(model_id):
        print(_c("33", f"Модель {model_id} не скачана — качаю при загрузке..."))
    print(_c("90", f"Загрузка {model_id} ..."))
    engine.load(model_id)
    print(_c("32", f"✓ {engine.model_id} | бэкенд: {engine.backend}"))


def stream_chat(message: str, history: list[dict]) -> str:
    from core import coordinator, safety
    safety.set_stop(False)
    out = ""
    try:
        for tok in coordinator.chat_stream(message, history=history):
            sys.stdout.write(tok)
            sys.stdout.flush()
            out += tok
    except KeyboardInterrupt:
        from core.engine import engine
        engine.request_stop()
        print(_c("90", " [прервано]"))
    print()
    return out


def run_agent(task: str) -> None:
    from core import agent_loop, safety
    safety.set_stop(False)
    try:
        for ev in agent_loop.run(task):
            t = ev.get("type")
            if t == "thought":
                print(_c("90", f"💭 {ev['text']}"))
            elif t == "tool":
                print(_c("36", f"🔧 {ev['name']}  {ev.get('args')}"))
            elif t == "result":
                r = ev.get("result", {})
                ok = r.get("ok")
                brief = "ok" if ok else f"ошибка: {r.get('error')}"
                if ok and "items" in r:
                    brief = f"ok — {len(r['items'])} элементов"
                elif ok and "content" in r:
                    brief = f"ok — {r.get('chars', 0)} символов"
                print(_c("32" if ok else "31", f"📤 {brief}"))
            elif t == "final":
                print(_c("1", "✅ ") + (ev.get("text") or ""))
            elif t == "error":
                print(_c("31", f"⚠ {ev.get('error')}"))
            elif t == "stopped":
                print(_c("90", "⏹ остановлено"))
    except KeyboardInterrupt:
        from core.engine import engine
        engine.request_stop()
        print(_c("90", " [прервано]"))


HELP = """Команды:
  /agent          переключить агент-режим (доступ к файлам/shell/web)
  /chat           обычный чат
  /models         список моделей
  /model <id>     /load <id>  — загрузить модель
  /clear          очистить историю
  /help           помощь
  /exit           выход"""


def repl(agent_mode: bool) -> None:
    from core.engine import engine
    from core import model_registry
    history: list[dict] = []
    print(_c("1", "Local AI CLI") + "  —  /help для команд, Ctrl+C прерывает генерацию")
    print(_c("90", f"режим: {'АГЕНТ' if agent_mode else 'чат'} | модель: {engine.model_id}"))
    while True:
        try:
            line = input(_c("34", "\n› ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line.startswith("/"):
            parts = line.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""
            if cmd in ("/exit", "/quit", "/q"):
                break
            elif cmd == "/help":
                print(HELP)
            elif cmd == "/agent":
                agent_mode = True; print(_c("90", "→ агент-режим"))
            elif cmd == "/chat":
                agent_mode = False; print(_c("90", "→ чат-режим"))
            elif cmd == "/clear":
                history = []; print(_c("90", "история очищена"))
            elif cmd == "/models":
                for m in model_registry.list_models():
                    mark = "●" if m["id"] == engine.model_id else ("✓" if m["downloaded"] else "·")
                    print(f"  {mark} {m['id']:<16} {m.get('name', '')}")
            elif cmd in ("/model", "/load"):
                if arg:
                    try:
                        load_model(arg)
                    except Exception as e:
                        print(_c("31", f"ошибка: {e}"))
                else:
                    print(_c("90", f"активная: {engine.model_id}"))
            else:
                print(_c("90", "неизвестная команда, /help"))
            continue
        if agent_mode:
            run_agent(line)
        else:
            ans = stream_chat(line, history)
            history.append({"role": "user", "content": line})
            history.append({"role": "assistant", "content": ans})
    print(_c("90", "Пока!"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Local AI CLI")
    ap.add_argument("--model", help="id модели из реестра")
    ap.add_argument("--agent", action="store_true", help="агент-режим (инструменты)")
    ap.add_argument("-p", "--prompt", help="один запрос и выход")
    args = ap.parse_args()

    from core.engine import last_model
    mid = args.model or last_model()
    try:
        load_model(mid)
    except Exception as e:
        print(_c("31", f"Не удалось загрузить модель {mid}: {e}"))
        sys.exit(1)

    if args.prompt:
        if args.agent:
            run_agent(args.prompt)
        else:
            stream_chat(args.prompt, [])
        return
    repl(args.agent)


if __name__ == "__main__":
    main()
