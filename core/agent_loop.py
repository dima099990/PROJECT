"""Автономный ReAct-цикл: рассуждение → вызов инструмента → результат → продолжение
до решения. Tool-call формат под Qwen3 (<tool_call>{json}</tool_call>) + фолбэк.
Стримит события (thought/tool/result/final) — для потокового отчёта в UI."""
from __future__ import annotations
import json
import re
from typing import Callable, Iterator

from core import safety, tools

TOOL_DOC = {
    "fs_list": "список файлов/папок: {path}",
    "fs_read": "прочитать файл: {path}",
    "fs_write": "записать файл: {path, content}",
    "fs_edit": "заменить фрагмент: {path, old, new}",
    "fs_move": "переместить: {src, dst}",
    "fs_delete": "удалить (в корзину): {path}",
    "fs_mkdir": "создать папку: {path}",
    "shell": "выполнить команду в терминале: {command}",
    "exec_python": "выполнить Python-код: {code}",
    "web_search": "поиск в интернете: {query}",
    "web_fetch": "скачать и извлечь текст страницы: {url}",
}


def system_prompt() -> str:
    lines = [f"- {n}: {d}" for n, d in TOOL_DOC.items()]
    return (
        "Ты — автономный агент управления ПК с полным доступом к файлам и терминалу. "
        "Чтобы вызвать инструмент, выведи строго:\n"
        "<tool_call>{\"name\":\"имя\",\"arguments\":{...}}</tool_call>\n"
        "Доступные инструменты:\n" + "\n".join(lines) +
        "\nДумай по шагам. Вызывай инструменты по одному. Когда задача решена — "
        "дай финальный ответ БЕЗ tool_call."
    )


# нормализованные имена инструментов (fslist -> fs_list, webfetch -> web_fetch и т.п.)
_NORM = {re.sub(r"[^a-z0-9]", "", k.lower()): k for k in TOOL_DOC}


def resolve_tool_name(name: str) -> str | None:
    if not name:
        return None
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return _NORM.get(key)


def parse_tool_calls(text: str) -> list[dict]:
    calls, seen = [], set()

    def _add(raw):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and obj.get("name") and raw not in seen:
                seen.add(raw)
                calls.append(obj)
        except Exception:
            pass

    # JSON-объект с одним уровнем вложенности (arguments — вложенный объект)
    obj = r"(\{(?:[^{}]|\{[^{}]*\})*\})"
    # <tool_call> / <toolcall> (подчёркивание/пробел опц., закрытие опц.)
    for m in re.findall(r"<tool[_\s]?call>\s*" + obj, text, re.S | re.I):
        _add(m)
    # ```json {...} ```
    for m in re.findall(r"```(?:json)?\s*" + obj + r"\s*```", text, re.S):
        _add(m)
    # голый JSON с "name" (последний фолбэк)
    if not calls:
        for m in re.findall(obj, text, re.S):
            if '"name"' in m:
                _add(m)
    return calls


def _default_generate(messages: list[dict]) -> str:
    from core.engine import engine
    return "".join(engine.generate_stream(messages))


def run(task: str, max_steps: int = 8,
        generate: Callable[[list[dict]], str] | None = None) -> Iterator[dict]:
    gen = generate or _default_generate
    messages = [{"role": "system", "content": system_prompt()},
                {"role": "user", "content": task}]
    for step in range(1, max_steps + 1):
        if safety.stop_requested():
            yield {"type": "stopped", "step": step}
            return
        try:
            out = gen(messages)
        except Exception as e:
            yield {"type": "error", "step": step, "error": f"генерация: {e}"}
            return
        calls = parse_tool_calls(out)
        if not calls:
            yield {"type": "final", "step": step, "text": out}
            return
        # убрать tool_call-разметку из видимой мысли (в т.ч. без закрывающего тега)
        thought = re.sub(r"<tool[_\s]?call>.*?(?:</tool[_\s]?call>|$)", "", out, flags=re.S | re.I).strip()
        if thought:
            yield {"type": "thought", "step": step, "text": thought}
        messages.append({"role": "assistant", "content": out})
        for call in calls:
            raw_name = call.get("name")
            name = resolve_tool_name(raw_name)
            args = call.get("arguments") or call.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            fn = tools.REGISTRY.get(name) if name else None
            yield {"type": "tool", "step": step, "name": name or raw_name, "args": args}
            try:
                res = fn(**args) if fn else {"ok": False, "error": f"неизвестный инструмент {raw_name}"}
            except Exception as e:
                res = {"ok": False, "error": str(e)}
            yield {"type": "result", "step": step, "name": name or raw_name, "result": res}
            messages.append({"role": "tool",
                             "content": json.dumps(res, ensure_ascii=False)[:4000]})
    yield {"type": "final", "step": max_steps, "text": "Достигнут лимит шагов."}
