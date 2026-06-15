# Local Autonomous AI — память проекта

> Человекочитаемый слой памяти. Корень не трогается авто-генерацией.
> В начале сессии: читать этот файл. В конце: обновлять статус/TODO.

## Цель
Локальный автономный мультиагентный ИИ на Qwen3 (safetensors / OpenVINO IR),
который работает СРАЗУ из коробки (без обучения), потом дообучается LoRA-адаптерами
под пользователя. Управляет ПК и ФС, веб-интерфейс, мультиагентность,
память диалогов, git-safe самоизменение кода.

## Стек
- Python 3.10+, кроссплатформа (Windows/Linux), CPU/CUDA/ROCm/MPS/OpenVINO
- Инференс: **transformers** (safetensors, CUDA/ROCm/MPS/CPU) + **OpenVINO** (Intel NPU/iGPU)
- Модели: huggingface_hub, реестр Qwen3 (0.6B–30B), кастомные GGUF через UI
- Бэкенд: FastAPI + uvicorn. Фронт: чистый HTML/CSS/JS, двуязычный (ru/en)
- Память/RAG: ChromaDB + sentence-transformers (multilingual)
- Поиск: duckduckgo-search (без ключа) + trafilatura
- Дообучение: transformers + peft (LoRA/QLoRA), фоновый поток, CPU/CUDA
- Самоизменение: git-safe (ветка → проверка → merge/откат)

## Железо (цель)
Galaxy Book 5 Pro 360, Intel Core Ultra 2, iGPU Arc 140V (без дискретной GPU),
16 ГБ RAM. Инференс и обучение разделены: тяжёлое обучение 14B+ локально
невозможно — только инференс; обучение локально 0.6B–3B.

## Структура
```
run.py            старт сервера (перезапуск из venv)
install.py        venv + зависимости + дефолтная модель (одна команда)
config.py         реестр моделей, агентов, пути, страховки, фича-флаги
core/
  engine/         бэкенды инференса: TorchEngine (CUDA/ROCm/MPS/CPU),
                  OVEngine (OpenVINO NPU/iGPU); фасад Engine
  model_registry  реестр моделей: список, скачивание, выбор активной
  coordinator     контекст + потоковая генерация
  agent_loop      ReAct-цикл (рассуждение → tool_call → результат → ...)
  agents          реестр агентов из .claude/agents/*.md
  tools           инструменты: fs, shell, exec_python, web_search/fetch
  safety          страховки: whitelist, стоп-флаг, корзина, лог
  chats           мультичат (chats.json)
  device          детект железа + выбор бэкенда
  metrics         psutil-метрики (CPU/RAM/диск)
  stats           статистика запросов
  parser          парсинг URL → корпус
  filesearch      поиск файлов по имени/содержимому
training/
  lora.py         LoRA-дообучение (+ Scratch, + Distill) в фоновом потоке
  adapters.py     реестр адаптеров: attach/detach к активной модели
memory/
  store.py        ChromaDB + RAG (PersistentClient, sentence-transformers)
selfmod/
  self_modify.py  git-safe самоизменение кода
scheduler/
  scheduler.py    APScheduler (заглушка, выключен)
web/api/
  app.py          FastAPI: чат, агент, модели, обучение, файлы, selfmod, WS
  auth.py         HMAC-авторизация по паролю
web/static/       index.html, app.js, style.css, i18n.js (панели, ru/en)
```

## Статус (реальный, 2025)

| Шаг | Что | Статус |
|-----|-----|--------|
| 1 | Каркас (структура, config, install, run, FastAPI, UI-панели) | ✅ **Готово** |
| 2 | Инференс-движок (Torch + OpenVINO, стриминг, чат) | ✅ **Готово** |
| 3 | Горячая перезагрузка модели из UI | ✅ **Готово** |
| 4 | Мультиагентность (ReAct-цикл, инструменты: fs/shell/python/web) | ✅ **Готово** |
| 5 | ChromaDB + RAG (memory/store.py, интеграция в чат) | ✅ **Готово** |
| 6 | LoRA-дообучение (adapter/scratch/distill, фоновый поток) | ✅ **Готово** |
| 7 | Self-modify (git-safe: ветка→проверка→merge/откат, история) | ✅ **Готово** |
| 8 | Модальности (STT/TTS/Vision) + Планировщик | ⬜ **Заглушка** |

## Session Log (auto-updated by AI after each session)
### 2025-06-16 (fix training crash + live chart + dataset viewer + crawl chart + server test)
- **Changed files**: `training/lora.py`, `core/parser.py`, `web/api/app.py`, `web/static/app.js`, `web/static/i18n.js`, `web/static/style.css`, `C:\Users\dima0\.claude\CLAUDE.md`, `C:\PROJECT\CLAUDE.md`
- **Fixes in `training/lora.py`**: crash 0xC0000005:
  1. `_train_full()` — загружает pre-trained веса, full fine-tune (не random)
  2. `_train_scratch_new()` — только random-weight (для scratch-моделей без весов)
  3. `_train_scratch()` диспетчер — выбирает между `_train_full` / `_train_scratch_new`
  4. `gradient_checkpointing_enable()` только под CUDA
  5. `gc.collect()` каждые 50 шагов во всех циклах
  6. `import gc`
- **New in `core/parser.py`**: `corpus_list()` (paginated 10k-char blocks), `corpus_delete_block()`, `corpus_clear()`
- **New in `web/api/app.py`**: `GET /api/data/corpus/content`, `DELETE /api/data/corpus/content/{block_id}`, `POST /api/data/corpus/clear`
- **New in `web/static/app.js`**:
  - **Chart**: 2 mini-charts (loss top, perplexity bottom), HiDPI via devicePixelRatio, легенда, обновление 1.5s
  - **Dataset viewer**: кнопка, пагинация по 10k chars, удалить блок, очистить всё
  - **Crawl chart**: canvas pages + chars, HiDPI, обновление 1s
  - **Panel persistence**: curPanel сохраняется в localStorage, восстанавливается при загрузке
  - **Fix**: crawl start btn id="cr-start-btn", stop btn id="cr-stop-btn2"
- **New in `web/static/i18n.js`**: строки датасета + кнопок (ru/en)
- **New in `web/static/style.css`**: `.dataset-block`, `.dataset-toolbar`, `.btn-xs`
- **Context persistence**: `C:\Users\dima0\.claude\CLAUDE.md` с START/END инструкциями; `C:\PROJECT\CLAUDE.md` с Session Log
- **Server test (2025-06-16)**: запущен ~13:00–14:30 на `http://127.0.0.1:8000`
  - Модель Qwen3-0.6B загружена (311 файлов safetensors, ~1 сек)
  - **Краша 0xC0000005 НЕТ** — fix подтверждён
  - **Краулинг**: сработал, страницы найдены, остановлен
  - **Датасет**: просмотр, удалено 4 блока
  - **Обучение**: запускалось 3 раза, без падений, поллинг статуса работал
  - **Панель**: после refresh сохранила последнюю открытую панель
  - Сервер остановлен

## Известные проблемы / риски
- **llama-cpp-python выпилен** — инференс через transformers / OpenVINO
- **Scratch-модели** — случайная инициализация, нужно много данных и эпох
- **Distill** — ученик не превзойдёт учителя без реальных данных
- **14B обучение** только на GPU-сервере (на CPU не влезет)
- **OpenVINO** показывает лучшую производительность на Intel Ultra NPU/iGPU
