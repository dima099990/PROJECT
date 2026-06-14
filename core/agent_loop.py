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


def parse_tool_calls(text: str) -> list[dict]:
    calls = []
    for m in re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, re.S):
        try:
            calls.append(json.loads(m))
        except Exception:
            pass
    if not calls:  # фолбэк: ```json {...} ```
        for m in re.findall(r"```(?:json)?\s*(\{.*?\"name\".*?\})\s*```", text, re.S):
            try:
                calls.append(json.loads(m))
            except Exception:
                pass
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
        out = gen(messages)
        calls = parse_tool_calls(out)
        if not calls:
            yield {"type": "final", "step": step, "text": out}
            return
        # убрать tool_call-разметку из видимой мысли
        thought = re.sub(r"<tool_call>.*?</tool_call>", "", out, flags=re.S).strip()
        if thought:
            yield {"type": "thought", "step": step, "text": thought}
        messages.append({"role": "assistant", "content": out})
        for call in calls:
            name = call.get("name")
            args = call.get("arguments") or {}
            fn = tools.REGISTRY.get(name)
            yield {"type": "tool", "step": step, "name": name, "args": args}
            res = fn(**args) if fn else {"ok": False, "error": f"неизвестный инструмент {name}"}
            yield {"type": "result", "step": step, "name": name, "result": res}
            messages.append({"role": "tool",
                             "content": json.dumps(res, ensure_ascii=False)[:4000]})
    yield {"type": "final", "step": max_steps, "text": "Достигнут лимит шагов."}
