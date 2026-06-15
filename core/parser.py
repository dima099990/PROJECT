from __future__ import annotations
import hashlib
import json
import re
import threading
import time
from urllib.parse import urljoin, urlparse

import config

CORPUS_DIR = config.DATA_DIR / "corpus"

crawl_status: dict = {
    "state": "idle",
    "start_url": "",
    "total": 0,
    "ok": 0,
    "errors": 0,
    "chars": 0,
    "pages": [],
    "error": None,
}
_crawl_thread: threading.Thread | None = None
_crawl_stop = threading.Event()


def _save_page(url: str, text: str) -> str:
    h = hashlib.sha1(url.encode()).hexdigest()[:12]
    (CORPUS_DIR / f"{h}.txt").write_text(text, encoding="utf-8")
    return h


def fetch_url(url: str) -> dict:
    import trafilatura
    html = ""
    try:
        html = trafilatura.fetch_url(url) or ""
    except Exception:
        html = ""
    if not html:
        try:
            import httpx
            r = httpx.get(url, timeout=20, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (LocalAI)"})
            html = r.text if r.status_code == 200 else ""
            if not html:
                return {"url": url, "ok": False, "error": f"HTTP {r.status_code}", "text": ""}
        except Exception as e:
            return {"url": url, "ok": False, "error": str(e), "text": ""}
    text = trafilatura.extract(html, include_comments=False, include_tables=True,
                               favor_recall=True) or ""
    if not text:
        try:
            from bs4 import BeautifulSoup
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        except Exception:
            text = ""
    if not text:
        return {"url": url, "ok": False, "error": "не удалось извлечь текст", "text": ""}
    return {"url": url, "ok": True, "chars": len(text), "text": text}


def _extract_links(html: str, base: str) -> list[str]:
    links = set()
    for m in re.finditer(r'href\s*=\s*["\'](.*?)["\']', html, re.I):
        raw = m.group(1).split("#")[0].split("?")[0].strip()
        if not raw or raw.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = urljoin(base, raw)
        parsed = urlparse(absolute)
        if parsed.scheme in ("http", "https"):
            links.add(absolute)
    return list(links)


def _same_domain(url: str, base: str) -> bool:
    return urlparse(url).netloc == urlparse(base).netloc


def _is_text_url(url: str) -> bool:
    skip_ext = {".pdf", ".zip", ".gz", ".tar", ".rar", ".7z", ".exe", ".msi",
                ".dmg", ".iso", ".mp3", ".mp4", ".avi", ".mov", ".jpg", ".jpeg",
                ".png", ".gif", ".webp", ".svg", ".ico", ".css", ".js", ".woff",
                ".woff2", ".eot", ".ttf"}
    path = urlparse(url).path.lower()
    for ext in skip_ext:
        if path.endswith(ext):
            return False
    return True


def _crawl(url: str, depth: int, max_pages: int) -> None:
    seen: set[str] = set()
    to_visit: list[tuple[str, int]] = [(url, 0)]
    parsed_base = urlparse(url)
    base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"

    while to_visit and not _crawl_stop.is_set():
        current_url, current_depth = to_visit.pop(0)
        if current_url in seen:
            continue
        if crawl_status["total"] >= max_pages:
            break
        seen.add(current_url)

        res = fetch_url(current_url)
        crawl_status["total"] += 1
        if res["ok"]:
            _save_page(current_url, res["text"])
            crawl_status["ok"] += 1
            crawl_status["chars"] += res["chars"]
            crawl_status["pages"].append({
                "url": current_url,
                "chars": res["chars"],
                "depth": current_depth,
            })
            if current_depth < depth:
                try:
                    import httpx
                    r = httpx.get(current_url, timeout=15, follow_redirects=True,
                                  headers={"User-Agent": "Mozilla/5.0 (LocalAI)"})
                    if r.status_code == 200:
                        for link in _extract_links(r.text, current_url):
                            if (_same_domain(link, current_url)
                                    and link not in seen
                                    and _is_text_url(link)):
                                to_visit.append((link, current_depth + 1))
                except Exception:
                    pass
        else:
            crawl_status["errors"] += 1

    if _crawl_stop.is_set():
        crawl_status["state"] = "stopped"
    else:
        crawl_status["state"] = "done"


def start_crawl(url: str, depth: int = 2, max_pages: int = 50) -> dict:
    global _crawl_thread
    if crawl_status["state"] in ("running",):
        return {"ok": False, "reason": "краулинг уже запущен"}
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    _crawl_stop.clear()
    crawl_status.update(state="running", start_url=url, total=0, ok=0, errors=0,
                        chars=0, pages=[], error=None)
    _crawl_thread = threading.Thread(target=_crawl, args=(url, depth, max_pages),
                                     daemon=True)
    _crawl_thread.start()
    return {"ok": True}


def stop_crawl() -> dict:
    _crawl_stop.set()
    return {"ok": True}


def get_crawl_status() -> dict:
    return dict(crawl_status)


def collect(urls: list[str]) -> dict:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    results, total_chars = [], 0
    for url in urls:
        url = url.strip()
        if not url:
            continue
        res = fetch_url(url)
        if res["ok"]:
            _save_page(url, res["text"])
            total_chars += res["chars"]
        results.append({k: res[k] for k in res if k != "text"})
    summary = {"ts": time.time(), "urls": len(results),
               "ok": sum(1 for r in results if r["ok"]),
               "chars": total_chars, "approx_tokens": total_chars // 4,
               "results": results}
    return summary


def corpus_stats() -> dict:
    if not CORPUS_DIR.exists():
        return {"files": 0, "chars": 0, "approx_tokens": 0}
    files = list(CORPUS_DIR.glob("*.txt"))
    chars = sum(f.stat().st_size for f in files)
    return {"files": len(files), "chars": chars, "approx_tokens": chars // 4}


CHUNK_SIZE = 10000


def corpus_list(page: int = 1, per_page: int = 10) -> dict:
    """List corpus files, each split into ~10k char chunks (pages)."""
    if not CORPUS_DIR.exists():
        return {"items": [], "total": 0, "page": page, "per_page": per_page}
    chunks: list[dict] = []
    for f in sorted(CORPUS_DIR.glob("*.txt")):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for offset in range(0, len(text), CHUNK_SIZE):
            chunk = text[offset:offset + CHUNK_SIZE]
            chunks.append({
                "id": f"{f.name}:{offset}",
                "file": f.name,
                "offset": offset,
                "text": chunk,
                "chars": len(chunk),
            })
    total = len(chunks)
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "items": chunks[start:end],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


def corpus_delete_block(block_id: str) -> bool:
    """Delete a single 10k-char block from a corpus file."""
    if ":" not in block_id:
        return False
    file_name, offset_str = block_id.split(":", 1)
    try:
        offset = int(offset_str)
    except ValueError:
        return False
    path = CORPUS_DIR / file_name
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    new_text = text[:offset] + text[offset + CHUNK_SIZE:]
    if new_text.strip():
        path.write_text(new_text, encoding="utf-8")
    else:
        path.unlink()
    return True


def corpus_clear() -> bool:
    """Delete all corpus files."""
    import shutil
    if CORPUS_DIR.exists():
        for f in CORPUS_DIR.glob("*.txt"):
            f.unlink()
    return True


_HISTORY_FILE = config.DATA_DIR / "parse_history.json"


def _load_history() -> dict:
    if _HISTORY_FILE.exists():
        try:
            return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_history(data: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_HISTORY_FILE)


def record_parse_stats(stats: dict) -> None:
    day = time.strftime("%Y-%m-%d")
    data = _load_history()
    entry = data.get(day, {"pages": 0, "chars": 0, "errors": 0})
    entry["pages"] += stats.get("ok", 0)
    entry["chars"] += stats.get("chars", 0)
    entry["errors"] += stats.get("errors", 0)
    data[day] = entry
    _save_history(data)


def parse_history() -> dict:
    return _load_history()
