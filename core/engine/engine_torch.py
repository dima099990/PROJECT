from __future__ import annotations
import gc
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
        self._is_peft = False

    def load(self, model_id: str) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from core import model_registry

        path = str(model_registry.ensure_model(model_id, backend=self.device_backend))
        kw: dict = {"trust_remote_code": True}
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
        else:
            kw["torch_dtype"] = torch.float32

        self.tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token

        self.model = AutoModelForCausalLM.from_pretrained(path, **kw)
        if be == "cpu":
            self.model.to("cpu")

        self.model.eval()
        self._is_peft = False
        self.backend = f"torch/{be}"
        self.model_id = model_id

    def load_adapter(self, path: str) -> None:
        from peft import PeftModel
        self.model = PeftModel.from_pretrained(self.model, path)
        self.model.eval()
        self._is_peft = True

    def detach_adapter(self) -> None:
        if self._is_peft and self.model_id:
            mid = self.model_id
            self.unload()
            self.load(mid)

    def _encode(self, messages: list[dict]) -> dict:
        import torch
        enc = None
        for extra in (
            {"enable_thinking": config.INFERENCE.get("thinking", False)},
            {},
        ):
            try:
                enc = self.tok.apply_chat_template(
                    messages, add_generation_prompt=True, return_tensors="pt",
                    return_dict=True, **extra)
                break
            except Exception:
                enc = None
        if enc is None or not hasattr(enc, "keys"):
            if enc is not None:
                enc = {"input_ids": enc}
            else:
                text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
                enc = self.tok(text, return_tensors="pt")
        return {k: v.to(self.model.device) for k, v in dict(enc).items()}

    def generate_stream(self, messages: list[dict], **kw) -> Iterator[str]:
        from transformers import TextIteratorStreamer
        self._stop = False
        inputs = self._encode(messages)
        streamer = TextIteratorStreamer(self.tok, skip_prompt=True,
                                        skip_special_tokens=True)
        gen_kw = dict(
            **inputs, streamer=streamer,
            max_new_tokens=kw.get("max_tokens") or config.INFERENCE["max_tokens"],
            do_sample=True,
            temperature=config.INFERENCE["temperature"],
            top_p=config.INFERENCE["top_p"],
            repetition_penalty=config.INFERENCE.get("repeat_penalty", 1.1),
            pad_token_id=(self.tok.pad_token_id if self.tok.pad_token_id is not None
                          else self.tok.eos_token_id),
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
        self._is_peft = False
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
