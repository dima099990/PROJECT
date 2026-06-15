from __future__ import annotations
import gc
import threading
import time

import config

status: dict = {
    "state": "idle", "progress": 0.0, "loss": None, "stage": "",
    "model_id": None, "step": 0, "total": 0, "adapter": None, "error": None,
    "warnings": [], "loss_history": [],
}
_thread: threading.Thread | None = None


def _step_update(step: int, total: int, loss_val: float) -> None:
    """Обновить прогресс + накопить историю лосса для графика."""
    lv = round(float(loss_val), 4)
    status["step"] = step
    status["total"] = total
    status["progress"] = round(step / total, 3) if total else 0.0
    status["loss"] = lv
    lh = status.setdefault("loss_history", [])
    lh.append({"step": step, "loss": lv})
    if len(lh) > 500:
        del lh[:-500]


def _save_training_history(model_id: str, mode: str, epochs: int, steps: int, loss: float) -> None:
    import json, time
    f = config.DATA_DIR / "training_history.json"
    history = []
    if f.exists():
        try:
            history = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    history.append({
        "ts": time.time(),
        "model_id": model_id,
        "mode": mode,
        "epochs": epochs,
        "steps": steps,
        "loss": loss,
    })
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(history[-50:], ensure_ascii=False), encoding="utf-8")

TARGET_MODULES_BY_ARCH: dict[str, list[str]] = {
    "llama": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "mistral": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "qwen2": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "gemma": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "falcon": ["query_key_value", "dense", "dense_h_to_4h", "dense_4h_to_h"],
    "gpt2": ["c_attn", "c_proj", "c_fc"],
}

def _detect_target_modules(model) -> list[str]:
    arch = getattr(model.config, "model_type", "").lower()
    for key, modules in TARGET_MODULES_BY_ARCH.items():
        if key in arch:
            return modules
    return ["q_proj", "k_proj", "v_proj", "o_proj"]

def _format_chat(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
        elif role == "system":
            lines.append(f"System: {content}")
        else:
            lines.append(f"{role}: {content}")
    lines.append("Assistant:")
    return "\n".join(lines)

def _default_tokenize(tok, text: str, max_length: int = 512):
    return tok(text, return_tensors="pt", truncation=True, max_length=max_length,
               padding="max_length")

def check_ram(model_id: str) -> list[str]:
    warnings = []
    m = config.MODEL_REGISTRY.get(model_id, {})
    if m.get("type") == "ov":
        warnings.append("OpenVINO-модели не поддерживают обучение (нужен safetensors)")
        return warnings
    if not m.get("trainable"):
        warnings.append("Модель отмечена как необучаемая в реестре")
        return warnings
    size_gb = m.get("size_gb", 0)
    if size_gb <= 0:
        warnings.append("Размер модели неизвестен — обучение может не влезть в RAM")
        return warnings
    try:
        import psutil
        total = psutil.virtual_memory().total / 1073741824
        avail = psutil.virtual_memory().available / 1073741824
    except Exception:
        total, avail = 0, 0
    estimate = size_gb * 2.5
    if avail > 0 and estimate > avail:
        swap = 0
        try:
            swap = psutil.swap_memory().free / 1073741824
        except Exception:
            pass
        total_free = avail + swap
        warnings.append(
            f"Модель ~{size_gb} ГБ, нужно ~{estimate:.0f} ГБ. "
            f"RAM: {avail:.0f} ГБ свободно из {total:.0f} ГБ, "
            f"своп: {swap:.0f} ГБ. "
            f"{'Будет использовать своп (может быть ~100x медленнее).' if total_free >= estimate else 'Даже со свопом не хватит — обучение упадёт с OutOfMemory.'}"
        )
    return warnings

def _collect_dataset(tok, max_samples: int = 300) -> list[str]:
    texts: list[str] = []
    try:
        from core import chats
        for c in chats.list_chats():
            full = chats.get_chat(c["id"]) or {}
            msgs = full.get("messages", [])
            for i in range(len(msgs) - 1):
                prev, cur = msgs[i], msgs[i + 1]
                if prev.get("role") == "user" and cur.get("role") == "assistant" and cur.get("content", "").strip():
                    pair = _format_chat([prev, cur])
                    texts.append(pair)
    except Exception as e:
        status.update(state="error", error=f"Ошибка загрузки чатов: {e}")
        return []
    cdir = config.DATA_DIR / "corpus"
    if cdir.exists():
        for f in sorted(cdir.glob("*.txt"))[:50]:
            try:
                t = f.read_text(encoding="utf-8", errors="ignore")
                for i in range(0, len(t), 1500):
                    chunk = t[i:i + 1500].strip()
                    if len(chunk) > 100:
                        texts.append(chunk)
            except Exception:
                pass
    return [x for x in texts if x.strip()][:max_samples]

def _train(model_id: str, epochs: int, lr: float, force: bool = False) -> None:
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import LoraConfig, get_peft_model
        from core import model_registry

        warnings = check_ram(model_id)
        if not force:
            ov_block = [w for w in warnings if "OpenVINO" in w]
            if ov_block:
                status.update(state="error", error=ov_block[0])
                return

        status.update(state="running", model_id=model_id, stage="загрузка модели",
                      error=None, progress=0.0, step=0, loss=None, adapter=None,
                      warnings=warnings)
        path = str(model_registry.ensure_model(model_id, backend="cpu"))

        tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token

        status["stage"] = "подготовка данных"
        texts = _collect_dataset(tok)
        if not texts:
            status.update(state="error",
                          error="нет данных: пообщайтесь в чате или спарсите сайты в корпус")
            return

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if (device == "cuda" and torch.cuda.get_device_capability() >= (8, 0)) else torch.float32
        if device == "cpu":
            dtype = torch.float32

        load_kw = {"torch_dtype": dtype, "trust_remote_code": True, "low_cpu_mem_usage": True}
        if device == "cuda":
            load_kw["device_map"] = "auto"
            try:
                size_gb = config.MODEL_REGISTRY.get(model_id, {}).get("size_gb", 0)
                if size_gb > 4:
                    from transformers import BitsAndBytesConfig
                    load_kw["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.bfloat16 if dtype == torch.bfloat16 else torch.float16,
                        bnb_4bit_quant_type="nf4")
            except Exception:
                pass

        model = AutoModelForCausalLM.from_pretrained(path, **load_kw)
        if device == "cpu":
            model.to("cpu")

        target_modules = _detect_target_modules(model)
        lconf = LoraConfig(
            r=8, lora_alpha=16, lora_dropout=0.05, task_type="CAUSAL_LM",
            target_modules=target_modules)
        model = get_peft_model(model, lconf)
        model.train()
        if torch.cuda.is_available():
            model.gradient_checkpointing_enable()
        if hasattr(torch, "compile") and device == "cuda":
            try:
                model = torch.compile(model)
            except Exception:
                pass

        opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
        total = len(texts) * epochs
        status.update(total=total, stage="обучение", step=0)
        step = 0
        for ep in range(epochs):
            for idx, text in enumerate(texts):
                if status["state"] == "stopping":
                    status.update(state="stopped", stage="остановлено")
                    return
                enc = _default_tokenize(tok, text)
                input_ids = enc["input_ids"].to(model.device)
                attention_mask = enc["attention_mask"].to(model.device)
                out = model(input_ids=input_ids, attention_mask=attention_mask, labels=input_ids)
                loss = out.loss
                loss.backward()
                opt.step()
                opt.zero_grad()
                step += 1
                _step_update(step, total, loss.item())
                if step % 50 == 0:
                    gc.collect()

        name = f"{model_id}-lora-{int(time.time())}"
        outdir = config.ADAPTERS_DIR / name
        outdir.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(outdir))
        tok.save_pretrained(str(outdir))
        try:
            from core import safety
            safety.log_action("train", {"model": model_id, "adapter": name,
                                        "steps": step, "loss": status["loss"]})
        except Exception:
            pass
        status.update(state="done", adapter=name, progress=1.0, stage="готово",
                      loss=float(status.get("loss") or 0))
        _save_training_history(model_id, "adapter", epochs, step, float(status.get("loss") or 0))
    except Exception as e:
        import traceback
        status.update(state="error", error=f"{e}\n{traceback.format_exc()[:500]}")

def _train_full(model_id: str, epochs: int, lr: float) -> None:
    """Full fine-tuning of an existing pre-trained model (all params)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from core import model_registry

    status.update(state="running", model_id=model_id,
                  stage="загрузка модели", error=None, progress=0.0, step=0, loss=None)

    path = str(model_registry.ensure_model(model_id, backend="cpu"))
    tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        path, torch_dtype=torch.float32, trust_remote_code=True, low_cpu_mem_usage=True)
    model.train()
    if torch.cuda.is_available():
        model.gradient_checkpointing_enable()

    status["stage"] = "подготовка данных"
    texts = _collect_dataset(tok)
    if not texts:
        status.update(state="error",
                      error="нет данных: пообщайтесь в чате или спарсите сайты в корпус")
        return

    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    total = len(texts) * epochs
    status.update(total=total, stage="полный fine-tune", step=0)
    step = 0
    for ep in range(epochs):
        for text in texts:
            if status["state"] == "stopping":
                status.update(state="stopped", stage="остановлено")
                return
            enc = _default_tokenize(tok, text)
            input_ids = enc["input_ids"]
            attention_mask = enc["attention_mask"]
            out = model(input_ids=input_ids, attention_mask=attention_mask, labels=input_ids)
            out.loss.backward()
            opt.step()
            opt.zero_grad()
            step += 1
            _step_update(step, total, out.loss.item())
            if step % 50 == 0:
                gc.collect()

    outdir = config.MODELS_CUSTOM_DIR / model_id
    outdir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(outdir))
    tok.save_pretrained(str(outdir))
    entry = config.MODEL_REGISTRY.get(model_id, {})
    entry["type"] = "hf"
    entry["trainable"] = True
    status.update(state="done", progress=1.0, stage="готово — модель сохранена")
    _save_training_history(model_id, "full-ft", epochs, step, float(status.get("loss") or 0))


def _train_scratch_new(model_id: str, epochs: int, lr: float) -> None:
    """Train a random-weight model from scratch (for scratch-type models)."""
    import torch
    from transformers import AutoTokenizer, LlamaConfig, LlamaForCausalLM
    spec = config.MODEL_REGISTRY.get(model_id, {})
    arch = spec.get("arch", {})
    status.update(state="running", model_id=model_id,
                  stage="токенизатор + архитектура",
                  error=None, progress=0.0, step=0, loss=None, adapter=None)

    tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-0.6B", trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    n_embd = int(arch.get("n_embd", 768))
    n_heads = int(arch.get("n_heads", 12))
    if n_embd % n_heads != 0:
        n_embd = (n_embd // n_heads) * n_heads
    cfg = LlamaConfig(
        vocab_size=len(tok),  # ОБЯЗАНО совпадать с токенизатором (иначе index out of range)
        hidden_size=n_embd,
        intermediate_size=n_embd * 4,
        num_hidden_layers=int(arch.get("n_layers", 12)),
        num_attention_heads=n_heads,
        num_key_value_heads=n_heads,
        max_position_embeddings=int(arch.get("n_ctx", 1024)))
    model = LlamaForCausalLM(cfg)
    model.train()
    if torch.cuda.is_available():
        model.gradient_checkpointing_enable()

    status["stage"] = "подготовка данных"
    texts = _collect_dataset(tok)
    if not texts:
        status.update(state="error",
                      error="нет данных: соберите корпус (панель Обучение -> Спарсить)")
        return

    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    total = len(texts) * epochs
    status.update(total=total, stage="pretrain с нуля", step=0)
    step = 0
    for ep in range(epochs):
        for text in texts:
            if status["state"] == "stopping":
                status.update(state="stopped", stage="остановлено")
                return
            enc = _default_tokenize(tok, text)
            input_ids = enc["input_ids"]
            attention_mask = enc["attention_mask"]
            out = model(input_ids=input_ids, attention_mask=attention_mask, labels=input_ids)
            out.loss.backward()
            opt.step()
            opt.zero_grad()
            step += 1
            _step_update(step, total, out.loss.item())
            if step % 50 == 0:
                gc.collect()

    outdir = config.MODELS_CUSTOM_DIR / model_id
    outdir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(outdir))
    tok.save_pretrained(str(outdir))
    entry = config.MODEL_REGISTRY.get(model_id, {})
    entry["type"] = "hf"
    entry["trainable"] = True
    status.update(state="done", progress=1.0, stage="готово — модель сохранена")
    _save_training_history(model_id, "scratch", epochs, step, float(status.get("loss") or 0))


def _train_scratch(model_id: str, epochs: int, lr: float) -> None:
    """Entry point for 'scratch' mode training.
    
    If model has existing weights on disk (pre-trained) → do full fine-tune.
    If model is a scratch-type (custom arch, no weights) → create random and train.
    """
    try:
        spec = config.MODEL_REGISTRY.get(model_id, {})
        path = config.model_path(model_id)
        is_scratch_type = spec.get("type") == "scratch"
        has_weights = path.exists() and any(path.iterdir())

        if is_scratch_type and not has_weights:
            _train_scratch_new(model_id, epochs, lr)
        else:
            _train_full(model_id, epochs, lr)
    except Exception as e:
        import traceback
        status.update(state="error", error=f"{e}\n{traceback.format_exc()[:500]}")

_DISTILL_SEEDS = [
    "Расскажи коротко о космосе.", "Объясни простыми словами, что такое вода.",
    "Дай определения слова 'компьютер'.", "Перечисли три времени года.",
    "Что такое солнце?", "Опиши, как работает дождь.",
    "Назови несколько фруктов.", "Зачем нужны книги?",
    "Что делает врач?", "Расскажи про кошек.",
]

def _train_distill(teacher_id: str, student_id: str, epochs: int, lr: float) -> None:
    try:
        from core.engine import engine as eng
        status.update(state="running", model_id=student_id,
                      stage=f"учитель {teacher_id} генерирует данные",
                      error=None, progress=0.0, step=0, loss=None, adapter=None)

        old_id = eng.model_id
        was_loaded = eng.loaded
        if eng.model_id != teacher_id:
            eng.load(teacher_id)
        cdir = config.DATA_DIR / "corpus"
        cdir.mkdir(parents=True, exist_ok=True)
        seeds = _DISTILL_SEEDS
        for i, seed in enumerate(seeds):
            if status["state"] == "stopping":
                status.update(state="stopped")
                if was_loaded and old_id and eng.model_id != old_id:
                    eng.load(old_id)
                return
            ans = "".join(eng.generate_stream([{"role": "user", "content": seed}],
                                              max_tokens=160))
            (cdir / f"distill_{int(time.time())}_{i}.txt").write_text(
                seed + "\n" + ans, encoding="utf-8")
            status.update(stage=f"генерация учителем {i + 1}/{len(seeds)}",
                          progress=round((i + 1) / len(seeds) * 0.4, 3))
            gc.collect()

        if was_loaded and old_id and eng.model_id != old_id:
            eng.load(old_id)

        if config.MODEL_REGISTRY.get(student_id, {}).get("type") == "scratch":
            _train_scratch(student_id, epochs, lr)
        else:
            _train(student_id, epochs, lr, force=True)
    except Exception as e:
        import traceback
        status.update(state="error", error=f"{e}\n{traceback.format_exc()[:500]}")
    finally:
        try:
            if was_loaded and old_id and eng.model_id != old_id:
                eng.load(old_id)
        except Exception:
            pass

def start_training(model_id: str, mode: str = "scratch",
                   teacher_id: str | None = None,
                   epochs: int = 1, lr: float = 2e-4,
                   force: bool = False) -> dict:
    global _thread
    status.update(warnings=[], loss_history=[], loss=None, step=0, progress=0.0, error=None)
    if mode not in ("adapter", "scratch", "distill"):
        return {"ok": False, "reason": "режим должен быть adapter/scratch/distill"}
    if status["state"] in ("running", "stopping"):
        return {"ok": False, "reason": "обучение уже идёт"}
    if model_id not in config.MODEL_REGISTRY:
        return {"ok": False, "reason": f"модель {model_id} не найдена в реестре"}

    if mode == "distill":
        if not teacher_id:
            return {"ok": False, "reason": "укажите модель-учителя"}
        if teacher_id not in config.MODEL_REGISTRY:
            return {"ok": False, "reason": f"учитель {teacher_id} не найден"}
        target, args = _train_distill, (teacher_id, model_id, epochs, lr)
    elif mode == "scratch":
        target, args = _train_scratch, (model_id, epochs, lr)
    else:
        warnings = check_ram(model_id)
        ov_block = [w for w in warnings if "OpenVINO" in w]
        if ov_block and not force:
            return {"ok": False, "reason": ov_block[0], "warnings": warnings}
        if warnings and not force:
            return {"ok": False, "reason": warnings[0], "warnings": warnings,
                    "hint": "если хотите рискнуть — используйте force=true"}
        target, args = _train, (model_id, epochs, lr, force)

    _thread = threading.Thread(target=target, args=args, daemon=True)
    _thread.start()
    return {"ok": True, "status": status}

def stop_training() -> dict:
    if status["state"] == "running":
        status["state"] = "stopping"
    return {"ok": True}
