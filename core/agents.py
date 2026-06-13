"""Реестр ИИ-агентов приложения (на активной модели, разные роли).
Шаг 1 — описания из config. Логика и инструменты подключаются на шаге 4."""
from __future__ import annotations
import config
from core import tools


def list_agents() -> list[dict]:
    out = []
    for aid, a in config.AGENT_REGISTRY.items():
        out.append({"id": aid, **a})
    return out


def agent_tools(agent_id: str) -> dict:
    names = config.AGENT_REGISTRY.get(agent_id, {}).get("tools", [])
    return {n: tools.REGISTRY[n] for n in names if n in tools.REGISTRY}
