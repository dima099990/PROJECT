from __future__ import annotations
import json
import re
from typing import Callable, Iterator

import config
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

_SYSTEM_PROMPT_EXTRA = (
    "Если нужно несколько действий — вызывай инструменты по одному, "
    "каждый раз дожидаясь результата. "
    "Когда задача полностью решена — дай финальный ответ.\n"
)

def system_prompt() -> str:
    lines = [f"- {n}: {d}" for n, d in TOOL_DOC.items()]
    return (
        "Ты — автономный агент управления ПК с полным доступом к файлам и терминалу. "
        "Чтобы вызвать инструмент, выведи строго:\n"
        "<tool_call>{\"name\":\"имя\",\"arguments\":{...}}</tool_call>\n"
        "Доступные инструменты:\n" + "\n".join(lines) +
        "\n" + _SYSTEM_PROMPT_EXTRA +
        "Думай по шагам. Вызывай инструменты по одному. Когда задача решена — "
        "дай финальный ответ БЕЗ tool_call."
    )

_NORM = {re.sub(r"[^a-z0-9]", "", k.lower()): k for k in TOOL_DOC}

def resolve_tool_name(name: str) -> str | None:
    if not name:
        return None
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    exact = _NORM.get(key)
    if exact:
        return exact
    for k, v in _NORM.items():
        if key in k or k in key:
            return v
    return None

def _extract_json_obj(text: str) -> list[str]:
    found = []
    depth, start = 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                found.append(text[start:i + 1])
                start = -1
    return found

def _try_parse_tool(raw: str) -> dict | None:
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and obj.get("name"):
            args = obj.get("arguments") or obj.get("args") or {}
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                args = {}
            return {"name": obj["name"], "arguments": args}
    except Exception:
        pass
    try:
        raw_fixed = re.sub(r"(?<!\\)'", '"', raw)
        raw_fixed = re.sub(r",\s*}", "}", raw_fixed)
        raw_fixed = re.sub(r",\s*]", "]", raw_fixed)
        obj = json.loads(raw_fixed)
        if isinstance(obj, dict) and obj.get("name"):
            args = obj.get("arguments") or obj.get("args") or {}
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                args = {}
            return {"name": obj["name"], "arguments": args}
    except Exception:
        pass
    return None

def parse_tool_calls(text: str) -> list[dict]:
    calls, seen = [], set()

    def _dedup(raw: str) -> dict | None:
        if raw in seen:
            return None
        seen.add(raw)
        return _try_parse_tool(raw)

    for m in re.findall(
        r"<tool[_\s]?call>\s*(.*?)\s*(?:</tool[_\s]?call>|$)",
        text, re.S | re.I,
    ):
        c = _dedup(m.strip())
        if c:
            calls.append(c)

    if not calls:
        for m in re.findall(
            r"```(?:json)?\s*(.*?)\s*```", text, re.S
        ):
            c = _dedup(m.strip())
            if c:
                calls.append(c)

    if not calls:
        for raw in _extract_json_obj(text):
            if '"name"' in raw:
                c = _dedup(raw)
                if c:
                    calls.append(c)

    return calls

def _default_generate(messages: list[dict]) -> str:
    from core.engine import engine
    max_tokens = max(
        config.INFERENCE.get("max_tokens", 1024),
        2048,
    )
    return "".join(engine.generate_stream(messages, max_tokens=max_tokens))


def run(
    task: str,
    max_steps: int = 8,
    generate: Callable[[list[dict]], str] | None = None,
) -> Iterator[dict]:
    gen = generate or _default_generate
    messages = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": task},
    ]
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

        thought = re.sub(
            r"<tool[_\s]?call>.*?(?:</tool[_\s]?call>|$)", "",
            out, flags=re.S | re.I,
        ).strip()
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
            yield {
                "type": "tool",
                "step": step,
                "name": name or (raw_name or "unknown"),
                "args": args,
            }

            try:
                if fn:
                    res = fn(**args)
                else:
                    available = ", ".join(tools.REGISTRY.keys())
                    res = {
                        "ok": False,
                        "error": f"неизвестный инструмент '{raw_name}'. "
                                 f"Доступны: {available}",
                    }
            except TypeError as e:
                res = {
                    "ok": False,
                    "error": f"ошибка аргументов {name}: {e}",
                }
            except Exception as e:
                res = {"ok": False, "error": str(e)}

            yield {
                "type": "result",
                "step": step,
                "name": name or raw_name,
                "result": res,
            }

            result_str = json.dumps(res, ensure_ascii=False)[:4000]
            messages.append({"role": "tool", "content": result_str})

    yield {
        "type": "final",
        "step": max_steps,
        "text": "Достигнут лимит шагов.",
    }
