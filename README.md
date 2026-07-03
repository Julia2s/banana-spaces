# ScientificTangle

ScientificTangle — evidence-first платформа для поиска и верификации научно-технических знаний в горно-металлургическом домене.

Превращает статьи, отчёты, патенты, XLSX/CSV-таблицы и справочники в проверяемую карту знаний: каждый факт в ответе сопровождается ссылкой на конкретный фрагмент источника.

## 1) Что реализовано в этой версии (v0.2)

### Backend (`services/gateway`)
- **Ingestion**: загрузка PDF/XLSX/CSV/DOCX/TXT/MD, lifecycle в PostgreSQL (`uploaded → queued → parsing → normalized → extracted → completed/failed`).
- **Normalization**: pypdf для PDF, openpyxl для XLSX (table blocks), python-docx для DOCX, csv для CSV. Каждая ячейка таблицы = отдельный SourceSpan с `row_index` + `column_name`.
- **Knowledge extraction**: rule-based (YAML-словари materials/processes/equipment с алиасами) + LLM-claims через YandexGPT. Все сущности и факты привязаны к source_span_id.
- **Knowledge graph**: Neo4j adapter с деградацией (если БД недоступна — методы no-op). Схема: Document → SourceSpan → Entity, Claim → SourceSpan + Entity.
- **Hybrid retrieval**: 3 канала — lexical (BM25), vector (sentence-transformers LaBSE или Yandex embeddings), table (поиск по ячейкам с числовым фильтром). Fusion с весами 0.4/0.35/0.25.
- **QueryIR**: парсит вопрос на сущности, числовые ограничения (`<=300 мг/л`), географию (Россия/зарубеж), временной диапазон (`последние 5 лет`), source_types, analysis_flags.
- **Answer synthesis**: YandexGPT 4 Pro по EvidenceBundle. Если LLM не настроен — extractive fallback с честной плашкой.
- **Audit**: middleware логирует все `/api/*` запросы в PostgreSQL `audit_events`.
- **Export**: Markdown и JSON из AnswerPayload.

### Инфраструктура
- Docker Compose: PostgreSQL 16, Neo4j 5, Qdrant 1.15, Redis 7, MinIO.
- Healthchecks на всех сервисах.
- Multistage Dockerfile для Gateway (сборка зависимостей ML отдельно от кода).

### Демо-данные
- `demo/seed_data/`: 4 файла по 4 официальным вопросам (обессоливание, католит, Au/Ag/МПГ, шахтные воды).

## 2) Быстрый запуск

### 2.1 Предварительные требования
- Python 3.11+ (рекомендован 3.12)
- Docker Desktop + Docker Compose
- Git

### 2.2 Запуск через Docker Compose

```bash
cp .env.example .env
# Отредактируйте .env: вставьте GATEWAY_YANDEX_FOLDER_ID и GATEWAY_YANDEX_IAM_TOKEN
docker compose up -d --build
```

Проверка:
- Health: http://127.0.0.1:8000/health
- OpenAPI: http://127.0.0.1:8000/api/docs
- Детальное здоровье: http://127.0.0.1:8000/api/health/detail

### 2.3 Локальный запуск Gateway (без compose)

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
pip install -e "services/gateway[dev]"

# Поднимите только PostgreSQL + Neo4j через compose
docker compose up -d postgres neo4j

uvicorn scientific_tangle_gateway.main:app --reload
```

### 2.4 Загрузка демо-корпуса

```bash
make seed
# или
python scripts/seed_demo.py --corpus demo/seed_data/
```

### 2.5 End-to-end smoke

```bash
make e2e
# или
python scripts/e2e_smoke.py
```

Скрипт задаёт два официальных вопроса и проверяет, что ответы содержат источники.

## 3) Переменные окружения

См. `.env.example`. Ключевые:

| Переменная | Назначение |
|---|---|
| `GATEWAY_DB_DSN` | PostgreSQL для task state + audit |
| `GATEWAY_NEO4J_URI` | Bolt-URI Neo4j |
| `GATEWAY_QDRANT_URL` | URL Qdrant (для будущего) |
| `GATEWAY_YANDEX_FOLDER_ID` | Folder ID в Yandex Cloud |
| `GATEWAY_YANDEX_IAM_TOKEN` | IAM-токен Yandex Cloud |
| `GATEWAY_EMBEDDINGS_BACKEND` | `sentence-transformers` (по умолчанию) или `yandex` |
| `GATEWAY_EMBEDDINGS_MODEL_NAME` | Модель sentence-transformers |
| `GATEWAY_AUDIT_ENABLED` | `true` — логировать все запросы |

**API-ключи НЕ коммитить.** Каждый разработчик создаёт `.env` локально.

## 4) API

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/documents/upload` | Загрузка файлов (multipart) |
| GET | `/api/tasks/{task_id}` | Статус задачи ingestion |
| POST | `/api/tasks/{task_id}/start` | Запуск обработки задачи |
| GET | `/api/tasks/{task_id}/documents` | Список нормализованных документов |
| GET | `/api/documents/{document_id}` | Получить NormalizedDocument |
| POST | `/api/retrieval/run` | Запуск retrieval (без synthesis) |
| GET | `/api/retrieval/runs/{run_id}` | Получить результат retrieval |
| POST | `/api/query` | Полный поток: QueryIR → retrieval → answer synthesis |
| GET | `/api/graph/evidence?entity=...` | Графовый поиск по сущности |
| GET | `/api/graph/subgraph?entity=...` | Локальный граф для UI |
| GET | `/api/graph/stats` | Статистика графа |
| GET | `/api/audit/events` | Список событий аудита |
| POST | `/api/export/markdown` | Экспорт ответа в Markdown |
| POST | `/api/export/json` | Экспорт ответа в JSON |

Полная спецификация: http://127.0.0.1:8000/api/docs

## 5) Архитектура

Модульный монолит внутри одного сервиса `gateway`:

```
services/gateway/src/scientific_tangle_gateway/
  main.py              ← FastAPI + lifespan + middleware
  config.py            ← настройки из .env
  schemas.py           ← Pydantic DTO
  routes_ingestion.py  ← /api/documents/*, /api/tasks/*
  routes_retrieval.py  ← /api/query, /api/retrieval/*, /api/graph/*
  routes_audit.py      ← /api/audit/*
  routes_export.py     ← /api/export/*

  # INGESTION
  ingestion.py         ← lifecycle
  normalization.py     ← PDF/XLSX/DOCX/CSV → NormalizedDocument
  task_repository.py   ← PostgreSQL: ingestion_tasks, ingestion_files
  task_worker.py       ← фоновый worker + extraction + Neo4j

  # KNOWLEDGE
  yandex_client.py     ← YandexGPT REST API обёртка
  extractor.py         ← rule-based + LLM extraction
  graph.py             ← Neo4j adapter
  claims.py            ← Claim builder, versioning
  embeddings.py        ← sentence-transformers / Yandex
  dictionaries/        ← YAML: materials, processes, equipment

  # RETRIEVAL
  query_ir.py          ← парсинг вопроса → QueryIR
  retrieval_engine.py  ← HybridRetrieval: lexical + vector + table + fusion

  # SYNTHESIS
  answer_builder.py    ← YandexGPT answer synthesis + fallback

  # AUDIT
  audit_middleware.py  ← логирование запросов
  audit_repository.py  ← PostgreSQL: audit_events
```

Подробное описание: `docs/project_structure.md`, план: `docs/PLAN_SHORT.md`, полное ТЗ: `docs/nauchny_klubok_top1_tz.md`.

## 6) Команды

```bash
make up              # поднять docker-compose
make down            # остановить
make logs            # логи всех сервисов
make install         # pip install -e services/gateway[dev]
make test            # pytest
make lint            # ruff
make seed            # загрузить demo corpus
make e2e             # один официальный вопрос end-to-end
make reset-demo      # удалить volumes и данные
```

## 7) Текущие ограничения

- Qdrant присутствует в compose, но индексация чанков в нём ещё не подключена (векторный retriever работает в памяти Gateway).
- LLM-extraction claims работает только при наличии `YANDEX_FOLDER_ID` и `YANDEX_IAM_TOKEN`. Без них — rule-based только.
- UI не входит в этот репозиторий, ему нужно реализовать отдельно (см. `docs/PLAN_SHORT.md` раздел 4).
- Развёрнутое облако для жюри — опционально, MVP-демо идёт через `docker compose up`.

## 8) Дорожная карта

См. `docs/PLAN_SHORT.md` — короткий рабочий план для команды 3-4 человека на 36 часов до дедлайна.
