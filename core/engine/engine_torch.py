"""Torch-бэкенд (transformers): CUDA / ROCm / MPS / CPU. Инференс от safetensors.
Потоковый вывод потокенно через TextIteratorStreamer + поток генерации."""
from __future__ import annotations
import threading
from typing import Iterator

import config
from core.engine.base import BaseEngine


class TorchEngine(BaseEngine):
    backend = "torch"

    def __init__(self, device_backend: str = "cpu") -> None:
        super().__init__()
        self.device_backend = device_backend
        self.model = None
        self.tok = None

    def load(self, model_id: str) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from core import model_registry

        path = str(model_registry.ensure_model(model_id, backend=self.device_backend))
        kw: dict = {}
        be = self.device_backend
        if be == "cuda":
            try:
                from transformers import BitsAndBytesConfig
                kw["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4")
            except Exception:
                kw["torch_dtype"] = torch.float16
            kw["device_map"] = "auto"
        elif be in ("rocm", "mps"):
            kw["torch_dtype"] = torch.float16
            kw["device_map"] = "auto"
        else:  # cpu
            kw["torch_dtype"] = torch.float32

        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForCausalLM.from_pretrained(path, **kw)
        if be == "cpu":
            self.model.to("cpu")
        self.backend = f"torch/{be}"
        self.model_id = model_id

    def _encode(self, messages: list[dict]):
        try:
            return self.tok.apply_chat_template(
                messages, add_generation_prompt=True, return_tensors="pt")
        except Exception:
            text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            return self.tok(text, return_tensors="pt").input_ids

    def generate_stream(self, messages: list[dict], **kw) -> Iterator[str]:
        from transformers import TextIteratorStreamer
        self._stop = False
        ids = self._encode(messages).to(self.model.device)
        streamer = TextIteratorStreamer(self.tok, skip_prompt=True, skip_special_tokens=True)
        gen_kw = dict(
            input_ids=ids, streamer=streamer,
            max_new_tokens=kw.get("max_tokens") or config.INFERENCE["max_tokens"],
            do_sample=True,
            temperature=config.INFERENCE["temperature"],
            top_p=config.INFERENCE["top_p"],
            repetition_penalty=config.INFERENCE.get("repeat_penalty", 1.1),
        )
        th = threading.Thread(target=self.model.generate, kwargs=gen_kw, daemon=True)
        th.start()
        for piece in streamer:
            if self._stop:
                break
            if piece:
                yield piece

    def unload(self) -> None:
        self.model = None
        self.tok = None
        self.model_id = None
        try:
            import torch, gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
