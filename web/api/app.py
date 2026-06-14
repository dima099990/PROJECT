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

import logging
import time
from logging.handlers import RotatingFileHandler

import config
from core import agentmgr, chats, coordinator, metrics, model_registry, parser, safety, stats
from core.engine import engine
from training import adapters, lora
from web.api.auth import check_password, issue_token, require_auth

STATIC = Path(__file__).resolve().parent.parent / "static"
app = FastAPI(title="Local Autonomous AI")

# --- Лог приложения (как в консоли) → logs/app.log ---
config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
_APP_LOG = config.LOGS_DIR / "app.log"
_h = RotatingFileHandler(_APP_LOG, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
for _n in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
    lg = logging.getLogger(_n)
    lg.addHandler(_h)
    if lg.level == logging.NOTSET:
        lg.setLevel(logging.INFO)


@app.on_event("startup")
def _startup_autoload():
    # Грузим активную/дефолтную модель в фоне, чтобы не блокировать старт сервера.
    import threading
    threading.Thread(target=__import__("core.engine", fromlist=["autoload"]).autoload,
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

class AgentReq(BaseModel):
    name: str
    description: str = ""
    prompt: str = ""
    model: str = "sonnet"
    id: str | None = None

class ParseReq(BaseModel):
    urls: list[str]

class ScratchReq(BaseModel):
    name: str
    n_layers: int = 12
    n_embd: int = 768
    n_heads: int = 12
    n_ctx: int = 1024
    vocab: int = 32000


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


# --- Агенты (CRUD над .claude/agents/*.md) ---
@app.get("/api/agents", dependencies=[Depends(require_auth)])
def agents_list():
    return {"agents": agentmgr.list_agents()}

@app.post("/api/agents", dependencies=[Depends(require_auth)])
def agents_save(req: AgentReq):
    aid = agentmgr.save_agent(req.name, req.description, req.prompt, req.model, req.id)
    return {"ok": True, "id": aid}

@app.delete("/api/agents/{agent_id}", dependencies=[Depends(require_auth)])
def agents_delete(agent_id: str):
    return {"ok": agentmgr.delete_agent(agent_id)}


# --- Модель с нуля (SCRATCH): регистрация архитектуры; обучение — Этап 7 ---
@app.post("/api/models/scratch", dependencies=[Depends(require_auth)])
def models_scratch(req: ScratchReq):
    # приблизительный подсчёт параметров трансформера
    p = req.n_layers * (12 * req.n_embd ** 2) + req.vocab * req.n_embd
    spec = {"name": req.name, "type": "scratch", "repo": "", "ov_repo": "", "hf_repo": "",
            "arch": req.model_dump(), "params_m": round(p / 1e6, 1),
            "size_gb": round(p * 2 / 1e9, 2), "trainable": True,
            "note": f"Своя сеть ~{round(p/1e6,1)}M параметров (обучение — Этап 7)"}
    mid = model_registry.add_model(spec)
    return {"ok": True, "id": mid, "params_m": spec["params_m"]}


# --- Статистика запросов (панель «Статус») ---
@app.get("/api/stats", dependencies=[Depends(require_auth)])
def stats_get():
    return stats.snapshot()


# --- Данные: парсинг сайтов в корпус (панель «Обучение») ---
@app.post("/api/data/parse", dependencies=[Depends(require_auth)])
def data_parse(req: ParseReq):
    return parser.collect(req.urls)

@app.get("/api/data/corpus", dependencies=[Depends(require_auth)])
def data_corpus():
    return parser.corpus_stats()


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
        acc, n, t0 = "", 0, time.time()
        try:
            for tok in coordinator.chat_stream(req.message, history=history):
                acc += tok; n += 1
                yield tok
                if safety.stop_requested():
                    break
        finally:
            chats.add_message(cid, "assistant", acc)
            stats.record(n, time.time() - t0, engine.model_id)

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8",
                             headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


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


# --- Логи: действия (actions.jsonl) + лог приложения (как в консоли) ---
@app.get("/api/logs", dependencies=[Depends(require_auth)])
def logs(limit: int = 200):
    f = config.LOGS_DIR / "actions.jsonl"
    actions = []
    if f.exists():
        for x in f.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                actions.append(json.loads(x))
            except Exception:
                pass
    app_lines = []
    if _APP_LOG.exists():
        app_lines = _APP_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    return {"lines": actions, "app": app_lines}


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
    engine.request_stop()
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
