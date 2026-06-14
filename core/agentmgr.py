"""Менеджер агентов: CRUD над .claude/agents/*.md (как у Claude Code).
Каждый агент = md-файл с фронтматтером (name/description/model) + системный промпт."""
from __future__ import annotations
import re

import config

AGENTS_DIR = config.ROOT / ".claude" / "agents"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "agent"


def _parse(text: str) -> dict:
    fm, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
        body = m.group(2)
    return {"name": fm.get("name", ""), "description": fm.get("description", ""),
            "model": fm.get("model", "sonnet"), "prompt": body.strip()}


def list_agents() -> list[dict]:
    if not AGENTS_DIR.exists():
        return []
    out = []
    for p in sorted(AGENTS_DIR.glob("*.md")):
        a = _parse(p.read_text(encoding="utf-8"))
        a["id"] = p.stem
        out.append(a)
    return out


def save_agent(name: str, description: str, prompt: str, model: str = "sonnet", agent_id: str | None = None) -> str:
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    aid = agent_id or _slug(name)
    text = (f"---\nname: {name}\ndescription: {description}\nmodel: {model}\n---\n\n{prompt.strip()}\n")
    (AGENTS_DIR / f"{aid}.md").write_text(text, encoding="utf-8")
    return aid


def delete_agent(agent_id: str) -> bool:
    p = AGENTS_DIR / f"{agent_id}.md"
    if p.exists():
        p.unlink()
        return True
    return False
