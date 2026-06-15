"""LoRA-дообучение БЕЗ GPU (CPU) в фоновом потоке — не блокирует чат.
Данные: диалоги из чатов + корпус (data/corpus). Адаптер сохраняется в data/adapters.
Реально для малых моделей (0.6B-1.7B); крупные — медленно/нужен GPU."""
from __future__ import annotations
import threading
import time

import config

# Статус обучения (отдаётся в UI: /api/status и /api/training/status)
status: dict = {
    "state": "idle", "progress": 0.0, "loss": None, "stage": "",
    "model_id": None, "step": 0, "total": 0, "adapter": None, "error": None,
}
_thread: threading.Thread | None = None


def can_train_locally(model_id: str) -> bool:
    m = config.MODEL_REGISTRY.get(model_id, {})
    return bool(m.get("trainable") or m.get("trainable_local")) and m.get("type") != "ov"


def _collect_dataset(tok, max_samples: int = 300) -> list[str]:
    texts: list[str] = []
    # 1) диалоги (user -> assistant), формат чата
    try:
        from core import chats
        for c in chats.list_chats():
            full = chats.get_chat(c["id"]) or {}
            msgs = full.get("messages", [])
            for i in range(len(msgs) - 1):
                if msgs[i]["role"] == "user" and msgs[i + 1]["role"] == "assistant" and msgs[i + 1]["content"].strip():
                    try:
                        texts.append(tok.apply_chat_template([msgs[i], msgs[i + 1]], tokenize=False))
                    except Exception:
                        texts.append(msgs[i]["content"] + "\n" + msgs[i + 1]["content"])
    except Exception:
        pass
    # 2) корпус (continued pretrain — сырой текст кусками)
    cdir = config.DATA_DIR / "corpus"
    if cdir.exists():
        for f in list(cdir.glob("*.txt"))[:50]:
            try:
                t = f.read_text(encoding="utf-8", errors="ignore")
                for i in range(0, len(t), 1500):
                    chunk = t[i:i + 1500].strip()
                    if len(chunk) > 100:
                        texts.append(chunk)
            except Exception:
                pass
    return [x for x in texts if x.strip()][:max_samples]


def _train(model_id: str, epochs: int, lr: float) -> None:
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import LoraConfig, get_peft_model
        from core import model_registry

        status.update(state="running", model_id=model_id, stage="загрузка модели",
                      error=None, progress=0.0, step=0, loss=None, adapter=None)
        path = str(model_registry.ensure_model(model_id, backend="cpu"))
        tok = AutoTokenizer.from_pretrained(path)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token

        status["stage"] = "подготовка данных"
        texts = _collect_dataset(tok)
        if not texts:
            status.update(state="error", error="нет данных: соберите корпус (панель «Обучение» → Спарсить) или пообщайтесь в чате")
            return

        model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.float32)
        lconf = LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05, task_type="CAUSAL_LM",
                           target_modules=["q_proj", "k_proj", "v_proj", "o_proj"])
        model = get_peft_model(model, lconf)
        model.train()
        opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)

        total = len(texts) * epochs
        status.update(total=total, stage="обучение", step=0)
        step = 0
        for _ in range(epochs):
            for text in texts:
                if status["state"] == "stopping":
                    status.update(state="stopped", stage="остановлено")
                    return
                enc = tok(text, return_tensors="pt", truncation=True, max_length=512)
                out = model(input_ids=enc["input_ids"], attention_mask=enc.get("attention_mask"),
                            labels=enc["input_ids"])
                loss = out.loss
                loss.backward()
                opt.step()
                opt.zero_grad()
                step += 1
                status.update(step=step, progress=round(step / total, 3), loss=round(float(loss.item()), 4))

        name = f"{model_id}-lora-{int(time.time())}"
        outdir = config.ADAPTERS_DIR / name
        outdir.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(outdir))
        try:
            from core import safety
            safety.log_action("train", {"model": model_id, "adapter": name, "steps": step, "loss": status["loss"]})
        except Exception:
            pass
        status.update(state="done", adapter=name, progress=1.0, stage="готово")
    except Exception as e:
        status.update(state="error", error=str(e))


def start_training(model_id: str, epochs: int = 1, lr: float = 2e-4) -> dict:
    global _thread
    if not can_train_locally(model_id):
        return {"ok": False, "reason": "Эта модель не дообучается локально (нужен GPU-сервер или safetensors-вариант)"}
    if status["state"] in ("running", "stopping"):
        return {"ok": False, "reason": "обучение уже идёт"}
    _thread = threading.Thread(target=_train, args=(model_id, epochs, lr), daemon=True)
    _thread.start()
    return {"ok": True, "status": status}


def stop_training() -> dict:
    if status["state"] == "running":
        status["state"] = "stopping"
    return {"ok": True}
