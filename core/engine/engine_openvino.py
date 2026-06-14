"""OpenVINO-бэкенд (Intel NPU/iGPU/CPU) через openvino-genai. Инференс от OV IR.
Потоковый вывод через callback-streamer. (Тестируется на железе с OpenVINO.)"""
from __future__ import annotations
import queue
import threading
from typing import Iterator

import config
from core.engine.base import BaseEngine


def _ov_device() -> str:
    """Лучшее доступное OV-устройство: NPU → GPU → CPU."""
    try:
        import openvino as ov
        avail = ov.Core().available_devices
        for d in ("NPU", "GPU"):
            if d in avail:
                return d
    except Exception:
        pass
    return "CPU"


class OVEngine(BaseEngine):
    backend = "openvino"

    def __init__(self) -> None:
        super().__init__()
        self.pipe = None

    def load(self, model_id: str) -> None:
        import openvino_genai as ov_genai
        from core import model_registry
        path = str(model_registry.ensure_model(model_id, backend="openvino"))
        dev = _ov_device()
        self.pipe = ov_genai.LLMPipeline(path, dev)
        self.backend = f"openvino/{dev}"
        self.model_id = model_id

    def _prompt(self, messages: list[dict]) -> str:
        # OV-pipeline обычно сам применяет chat-template; на всякий — простой формат.
        return "\n".join(f"{m['role']}: {m['content']}" for m in messages) + "\nassistant:"

    def generate_stream(self, messages: list[dict], **kw) -> Iterator[str]:
        import openvino_genai as ov_genai
        self._stop = False
        q: queue.Queue = queue.Queue()

        def cb(token: str):
            q.put(token)
            return self._stop  # True → остановить генерацию

        cfg = ov_genai.GenerationConfig()
        cfg.max_new_tokens = kw.get("max_tokens") or config.INFERENCE["max_tokens"]
        cfg.temperature = config.INFERENCE["temperature"]
        cfg.top_p = config.INFERENCE["top_p"]
        cfg.do_sample = True

        def run():
            try:
                self.pipe.generate(self._prompt(messages), cfg, cb)
            finally:
                q.put(None)

        threading.Thread(target=run, daemon=True).start()
        while True:
            tok = q.get()
            if tok is None:
                break
            yield tok

    def unload(self) -> None:
        self.pipe = None
        self.model_id = None
