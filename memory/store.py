from __future__ import annotations
import json
import threading
import time
from pathlib import Path

import config

COLLECTION_NAME = config.MEMORY.get("collection", "dialogs")
EMBED_MODEL = config.MEMORY.get("embeddings_model",
                                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

_embed_fn = None
_embed_lock = threading.Lock()


def _get_embedder():
    global _embed_fn
    if _embed_fn is not None:
        return _embed_fn
    with _embed_lock:
        if _embed_fn is not None:
            return _embed_fn
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(EMBED_MODEL)
            _embed_fn = lambda texts: model.encode(texts, show_progress_bar=False).tolist()
        except Exception as e:
            _embed_fn = lambda texts: [[0.0] * 384 for _ in texts]
    return _embed_fn


class MemoryStore:
    def __init__(self) -> None:
        self._client = None
        self._collection = None
        self._init_lock = threading.Lock()
        self._ready = False

    def _ensure(self) -> bool:
        if self._ready:
            return True
        with self._init_lock:
            if self._ready:
                return True
            try:
                import chromadb
                chroma_path = str(config.CHROMA_DIR)
                self._client = chromadb.PersistentClient(path=chroma_path)
                try:
                    self._collection = self._client.get_collection(COLLECTION_NAME)
                except Exception:
                    self._collection = self._client.create_collection(COLLECTION_NAME)
                self._ready = True
                return True
            except Exception as e:
                print(f"[memory] ChromaDB init failed: {e}")
                return False

    def add(self, role: str, text: str, meta: dict | None = None) -> None:
        if not text or not text.strip():
            return
        meta = dict(meta or {})
        meta["role"] = role
        meta["ts"] = time.time()
        if not self._ensure():
            return
        try:
            embedder = _get_embedder()
            emb = embedder([text])
            uid = f"{int(time.time() * 1e6)}_{hash(text) % (2**31)}"
            self._collection.add(
                ids=[uid],
                embeddings=emb,
                documents=[text],
                metadatas=[meta])
        except Exception as e:
            print(f"[memory] add error: {e}")

    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        k = top_k or config.MEMORY.get("rag_top_k", 5)
        results = []
        if not self._ensure():
            return results
        try:
            embedder = _get_embedder()
            q_emb = embedder([query])
            raw = self._collection.query(query_embeddings=q_emb, n_results=k)
            if raw and raw.get("ids"):
                for i in range(len(raw["ids"][0])):
                    results.append({
                        "id": raw["ids"][0][i],
                        "text": raw["documents"][0][i] if raw.get("documents") else "",
                        "meta": raw["metadatas"][0][i] if raw.get("metadatas") else {},
                        "score": raw["distances"][0][i] if raw.get("distances") else 0,
                    })
        except Exception as e:
            print(f"[memory] search error: {e}")
        return results

    def history(self, limit: int = 50) -> list[dict]:
        results = []
        if not self._ensure():
            return results
        try:
            count = self._collection.count()
            raw = self._collection.get(limit=min(limit, count),
                                       offset=max(0, count - limit))
            if raw and raw.get("ids"):
                for i in range(len(raw["ids"])):
                    meta = raw["metadatas"][i] if raw.get("metadatas") else {}
                    results.append({
                        "id": raw["ids"][i],
                        "text": raw["documents"][i] if raw.get("documents") else "",
                        "role": meta.get("role", ""),
                        "ts": meta.get("ts", 0),
                    })
                results.sort(key=lambda x: x.get("ts", 0), reverse=False)
        except Exception as e:
            print(f"[memory] history error: {e}")
        return results

    def clear(self) -> None:
        if not self._ensure():
            return
        try:
            all_ids = self._collection.get()["ids"]
            if all_ids:
                self._collection.delete(ids=all_ids)
        except Exception as e:
            print(f"[memory] clear error: {e}")

    @property
    def count(self) -> int:
        if not self._ensure():
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0


store = MemoryStore()
