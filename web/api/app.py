"""FastAPI приложение: авторизация, панели, базовый чат, реестр/переключение
моделей, статус-апдейты по WebSocket. Вся логика за REST (задел под REMOTE)."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from core import agents, chats, coordinator, metrics, model_registry, safety
from core.inference import engine
from training import adapters, lora
from web.api.auth import check_password, issue_token, require_auth

STATIC = Path(__file__).resolve().parent.parent / "static"
app = FastAPI(title="Local Autonomous AI")


@app.on_event("startup")
def _startup_autoload():
    # Грузим активную/дефолтную модель в фоне, чтобы не блокировать старт сервера.
    import threading
    threading.Thread(target=__import__("core.inference", fromlist=["autoload"]).autoload,
                     daemon=True).start()


# --- Модели запросов ---
class LoginReq(BaseModel):
    password: str

class ChatReq(BaseModel):
    message: str
    history: list[dict] | None = None

class ModelReq(BaseModel):
    model_id: str

class WorkDirsReq(BaseModel):
    work_dirs: list[str]

class MsgReq(BaseModel):
    message: str

class TitleReq(BaseModel):
    title: str

class AddModelReq(BaseModel):
    name: str
    repo: str
    filename: str
    quant: str | None = ""
    size_gb: float | None = 0
    note: str | None = ""
    trainable_local: bool | None = False


# --- Авторизация ---
@app.post("/api/login")
def login(req: LoginReq):
    if not check_password(req.password):
        return JSONResponse({"ok": False}, status_code=401)
    return {"ok": True, "token": issue_token()}


# --- Статус системы ---
@app.get("/api/status", dependencies=[Depends(require_auth)])
def status():
    return {
        "deploy_mode": config.DEPLOY_MODE,
        "model_loaded": engine.loaded,
        "active_model": engine.model_id,
        "active_adapter": adapters.active_adapter,
        "training": lora.status,
        "stop_flag": safety.stop_requested(),
        "features": config.FEATURES,
    }


# --- Модели: список / загрузка / переключение (горячая перезагрузка) ---
@app.get("/api/models", dependencies=[Depends(require_auth)])
def models():
    return {"models": model_registry.list_models(), "active": engine.model_id}

@app.post("/api/models/load", dependencies=[Depends(require_auth)])
def models_load(req: ModelReq):
    engine.load(req.model_id)  # качает при необходимости + грузит
    return {"ok": True, "active": engine.model_id}

@app.get("/api/models/repo_files", dependencies=[Depends(require_auth)])
def models_repo_files(repo: str):
    try:
        return {"files": model_registry.repo_files(repo)}
    except Exception as e:
        return JSONResponse({"files": [], "error": str(e)}, status_code=400)

@app.post("/api/models/add", dependencies=[Depends(require_auth)])
def models_add(req: AddModelReq):
    try:
        mid = model_registry.add_model(req.model_dump(exclude_none=True))
        return {"ok": True, "id": mid}
    except Exception as e:
        return JSONResponse({"ok": False, "reason": str(e)}, status_code=400)

@app.delete("/api/models/{model_id}", dependencies=[Depends(require_auth)])
def models_remove(model_id: str):
    return {"ok": model_registry.remove_model(model_id)}


# --- Агенты ---
@app.get("/api/agents", dependencies=[Depends(require_auth)])
def agents_list():
    return {"agents": agents.list_agents()}


# --- Адаптеры (LoRA) ---
@app.get("/api/adapters", dependencies=[Depends(require_auth)])
def adapters_list():
    return {"adapters": adapters.list_adapters(), "active": adapters.active_adapter}


# --- Чаты (несколько диалогов) ---
@app.get("/api/chats", dependencies=[Depends(require_auth)])
def chats_list():
    return {"chats": chats.list_chats()}

@app.post("/api/chats", dependencies=[Depends(require_auth)])
def chats_create():
    return chats.create_chat()

@app.get("/api/chats/{cid}", dependencies=[Depends(require_auth)])
def chats_get(cid: str):
    c = chats.get_chat(cid)
    if not c:
        return JSONResponse({"ok": False}, status_code=404)
    return {"id": c["id"], "title": c["title"], "messages": c["messages"]}

@app.delete("/api/chats/{cid}", dependencies=[Depends(require_auth)])
def chats_delete(cid: str):
    return {"ok": chats.delete_chat(cid)}

@app.patch("/api/chats/{cid}", dependencies=[Depends(require_auth)])
def chats_rename(cid: str, req: TitleReq):
    return {"ok": chats.rename_chat(cid, req.title)}

# --- Потоковый чат: стримит токены, сохраняет диалог ---
@app.post("/api/chats/{cid}/message", dependencies=[Depends(require_auth)])
def chats_message(cid: str, req: MsgReq):
    if not engine.loaded:
        return JSONResponse({"ok": False, "reason": "Модель не загружена"}, status_code=409)
    chat = chats.get_chat(cid)
    if not chat:
        return JSONResponse({"ok": False}, status_code=404)
    history = list(chat["messages"])
    chats.add_message(cid, "user", req.message)
    safety.log_action("chat", {"chat": cid, "msg": req.message[:120]})

    def gen():
        acc = ""
        try:
            for tok in coordinator.chat_stream(req.message, history=history):
                acc += tok
                yield tok
                if safety.stop_requested():
                    break
        finally:
            chats.add_message(cid, "assistant", acc)

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


# --- Метрики системы (CPU/RAM/диск) ---
@app.get("/api/metrics", dependencies=[Depends(require_auth)])
def metrics_get():
    return metrics.snapshot()


# --- Файлы (шаг 4) ---
@app.get("/api/files", dependencies=[Depends(require_auth)])
def files(path: str = "."):
    p = Path(path)
    if not p.exists():
        return {"ok": False, "items": []}
    items = [{"name": c.name, "dir": c.is_dir()} for c in sorted(p.iterdir())]
    return {"ok": True, "path": str(p.resolve()), "items": items,
            "writable": safety.is_writable(p)}


# --- Логи действий ---
@app.get("/api/logs", dependencies=[Depends(require_auth)])
def logs(limit: int = 100):
    f = config.LOGS_DIR / "actions.jsonl"
    if not f.exists():
        return {"lines": []}
    lines = f.read_text(encoding="utf-8").splitlines()[-limit:]
    return {"lines": [json.loads(x) for x in lines]}


# --- Страховки: рабочие папки + стоп-кнопка ---
@app.get("/api/safety", dependencies=[Depends(require_auth)])
def safety_get():
    return {"work_dirs": config.SAFETY["work_dirs"], "stop_flag": safety.stop_requested()}

@app.post("/api/safety/workdirs", dependencies=[Depends(require_auth)])
def safety_workdirs(req: WorkDirsReq):
    config.SAFETY["work_dirs"] = req.work_dirs
    return {"ok": True, "work_dirs": config.SAFETY["work_dirs"]}

@app.post("/api/safety/stop", dependencies=[Depends(require_auth)])
def safety_stop():
    safety.set_stop(True)
    return {"ok": True, "stop_flag": True}

@app.post("/api/safety/resume", dependencies=[Depends(require_auth)])
def safety_resume():
    safety.set_stop(False)
    return {"ok": True, "stop_flag": False}


# --- Обучение (шаг 6) ---
@app.post("/api/training/start", dependencies=[Depends(require_auth)])
def training_start(req: ModelReq):
    return lora.start_training(req.model_id)


# --- WebSocket: статус-апдейты (что агент делает сейчас) ---
@app.websocket("/ws/status")
async def ws_status(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json({
                "model": engine.model_id,
                "training": lora.status,
                "stop_flag": safety.stop_requested(),
                "metrics": metrics.snapshot(),
            })
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass


# --- Статика (UI) ---
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
