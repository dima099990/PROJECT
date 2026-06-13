"""Хранилище чат-сессий (несколько диалогов). Персист в data/chats.json.
Сообщения хранятся сырыми, включая <think>-блоки модели."""
from __future__ import annotations
import json
import threading
import time
import uuid

import config

_FILE = config.DATA_DIR / "chats.json"
_lock = threading.Lock()


def _load() -> dict:
    if _FILE.exists():
        try:
            return json.loads(_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"chats": {}}


def _save(db: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_FILE)


def list_chats() -> list[dict]:
    db = _load()
    items = [
        {"id": c["id"], "title": c["title"], "created": c["created"], "updated": c["updated"]}
        for c in db["chats"].values()
    ]
    return sorted(items, key=lambda x: x["updated"], reverse=True)


def create_chat(title: str = "Новый чат") -> dict:
    with _lock:
        db = _load()
        cid = uuid.uuid4().hex[:12]
        now = time.time()
        db["chats"][cid] = {"id": cid, "title": title, "created": now, "updated": now, "messages": []}
        _save(db)
    return {"id": cid, "title": title}


def get_chat(cid: str) -> dict | None:
    return _load()["chats"].get(cid)


def delete_chat(cid: str) -> bool:
    with _lock:
        db = _load()
        if cid in db["chats"]:
            del db["chats"][cid]
            _save(db)
            return True
    return False


def rename_chat(cid: str, title: str) -> bool:
    with _lock:
        db = _load()
        if cid in db["chats"]:
            db["chats"][cid]["title"] = title
            db["chats"][cid]["updated"] = time.time()
            _save(db)
            return True
    return False


def add_message(cid: str, role: str, content: str) -> None:
    with _lock:
        db = _load()
        c = db["chats"].get(cid)
        if not c:
            return
        c["messages"].append({"role": role, "content": content})
        c["updated"] = time.time()
        # авто-заголовок из первого сообщения пользователя
        if role == "user" and c["title"] in ("Новый чат", "New chat") and content.strip():
            c["title"] = content.strip()[:40]
        _save(db)
