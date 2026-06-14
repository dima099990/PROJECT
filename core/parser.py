"""Парсер сайтов для обучающего корпуса: URL → основной текст (trafilatura).
Результат складывается в data/corpus/. Используется панелью «Обучение»/«Данные»."""
from __future__ import annotations
import hashlib
import json
import time

import config

CORPUS_DIR = config.DATA_DIR / "corpus"


def fetch_url(url: str) -> dict:
    """Скачать страницу и извлечь основной текст (несколько стратегий)."""
    import trafilatura  # lazy
    html = ""
    # 1) штатная загрузка trafilatura (надёжнее по кодировке/сжатию)
    try:
        html = trafilatura.fetch_url(url) or ""
    except Exception:
        html = ""
    # 2) фолбэк httpx
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
        # 3) последний фолбэк — голый текст из html
        try:
            from bs4 import BeautifulSoup
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        except Exception:
            text = ""
    if not text:
        return {"url": url, "ok": False, "error": "не удалось извлечь текст", "text": ""}
    return {"url": url, "ok": True, "chars": len(text), "text": text}


def collect(urls: list[str]) -> dict:
    """Спарсить список URL, сохранить в корпус. Вернуть сводку."""
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    results, total_chars = [], 0
    for url in urls:
        url = url.strip()
        if not url:
            continue
        res = fetch_url(url)
        if res["ok"]:
            h = hashlib.sha1(url.encode()).hexdigest()[:12]
            (CORPUS_DIR / f"{h}.txt").write_text(res["text"], encoding="utf-8")
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
