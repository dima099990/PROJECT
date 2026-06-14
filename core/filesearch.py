"""Поиск файлов по имени и (опц.) содержимому — по всему диску/выбранным путям.
Кроссплатформенно. Ограничения по числу результатов и размеру файла."""
from __future__ import annotations
import os
from pathlib import Path

_TEXT_EXT = {".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".html", ".css",
             ".java", ".c", ".cpp", ".go", ".rs", ".rb", ".php", ".sh", ".yml",
             ".yaml", ".xml", ".ini", ".cfg", ".log", ".sql"}
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "$Recycle.Bin",
              "System Volume Information", "Windows", "ProgramData"}


def search(query: str, root: str = ".", by_content: bool = False,
           max_results: int = 200, max_file_mb: int = 5) -> dict:
    base = Path(root).expanduser()
    q = query.lower()
    hits = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            scanned += 1
            p = Path(dirpath) / fn
            name_hit = q in fn.lower()
            content_hit = False
            if by_content and not name_hit and p.suffix.lower() in _TEXT_EXT:
                try:
                    if p.stat().st_size <= max_file_mb * 1048576:
                        if q in p.read_text(encoding="utf-8", errors="ignore").lower():
                            content_hit = True
                except Exception:
                    pass
            if name_hit or content_hit:
                try:
                    st = p.stat()
                    hits.append({"path": str(p), "name": fn, "size": st.st_size,
                                 "match": "content" if content_hit else "name"})
                except Exception:
                    pass
                if len(hits) >= max_results:
                    return {"ok": True, "query": query, "root": str(base),
                            "scanned": scanned, "truncated": True, "results": hits}
    return {"ok": True, "query": query, "root": str(base), "scanned": scanned,
            "truncated": False, "results": hits}
