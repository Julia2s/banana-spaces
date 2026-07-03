# Структура проекта

Этот файл — навигационный контекст для команды и ИИ-агентов. Поддерживается вручную.

## Обязательное правило синхронизации

Когда в проекте появляются новые значимые директории, сервисы, пакеты, контракты, схемы, миграции, инфраструктурные файлы — обновляй этот файл в той же рабочей сессии.

## Текущая структура

### Корень

- `README.md` — описание проекта, быстрый запуск, API.
- `Makefile` — команды разработки: up, down, build, logs, test, lint, seed, e2e, reset-demo.
- `docker-compose.yml` — локальный стек: Gateway, PostgreSQL, Neo4j, Qdrant, Redis, MinIO.
- `.env.example` — пример переменных окружения (с YandexGPT).
- `.gitignore` — исключения.
- `.cursor/rules/project.mdc` — always-on правила для Cursor.

### docs/

- `PLAN_SHORT.md` — короткий рабочий план для команды (приоритетный документ).
- `nauchny_klubok_top1_tz.md` — полное ТЗ (596 строк, историческое).
- `project_structure.md` — этот файл.

### shared/contracts/

JSON Schema контракты (статус draft, заморожены после Sync 1):

- `answer_payload.schema.json` — финальный ответ UI.
- `document_artifact.schema.json` — краткое описание сохранённого normalized artifact.
- `evidence_bundle.schema.json` — набор доказательств retrieval.
- `ingestion_task.schema.json` — статус задачи загрузки.
- `normalized_document.schema.json` — нормализованный документ.
- `query_ir.schema.json` — типизированный план запроса.
- `retrieval_document.schema.json` — единица retrieval-корпуса.
- `retrieval_run.schema.json` — результат запуска QueryIR + retrieval.
- `source_span.schema.json` — доказательный фрагмент источника.
- `README.md` — статус контрактов.

### services/gateway/

Первый и единственный backend-сервис MVP. FastAPI.

- `Dockerfile` — multistage build (builder + runtime).
- `pyproject.toml` — зависимости: fastapi, psycopg, pypdf, openpyxl, python-docx, neo4j, httpx, pyyaml, numpy; опционально sentence-transformers.
- `README.md` — назначение Gateway (legacy).
- `src/scientific_tangle_gateway/` — исходный код.
  - `__init__.py`
  - `main.py` — точка сборки FastAPI, lifespan, middleware.
  - `config.py` — Settings (pydantic-settings).
  - `schemas.py` — Pydantic DTO (контракты для UI).
  - `routes_ingestion.py` — `/api/documents/*`, `/api/tasks/*`.
  - `routes_retrieval.py` — `/api/query`, `/api/retrieval/*`, `/api/graph/*`.
  - `routes_audit.py` — `/api/audit/*`.
  - `routes_export.py` — `/api/export/*`.
  - `ingestion.py` — lifecycle ingestion task, локальное сохранение загруженных файлов.
  - `normalization.py` — парсинг PDF/XLSX/CSV/DOCX/TXT/MD → NormalizedDocument + SourceSpan. Таблицы с cell-level provenance.
  - `task_repository.py` — PostgreSQL: ingestion_tasks, ingestion_files.
  - `task_worker.py` — фоновый polling worker + extraction + запись в Neo4j.
  - `yandex_client.py` — обёртка над YandexGPT REST API (chat, chat_json, embed_texts).
  - `extractor.py` — KnowledgeExtractor: rule-based (DictionaryLoader + RuleBasedExtractor) + LLM (LLMClaimExtractor).
  - `graph.py` — Neo4j adapter (KnowledgeGraph): schema init, write Document/SourceSpan/Entity/Claim, find_evidence_by_entity, find_related_entities.
  - `claims.py` — Claim builder, статусы, detect_conflicts.
  - `embeddings.py` — EmbeddingsProvider: sentence-transformers (по умолчанию) или Yandex embeddings, fallback на hashing.
  - `query_ir.py` — QueryIRBuilder: entities, numeric_constraints, geo_scope, time_range, source_types, analysis_flags.
  - `retrieval_engine.py` — HybridRetrievalService: LexicalRetriever (BM25), VectorRetriever (embeddings), TableRetriever (поиск по ячейкам с числовым фильтром), NumericFilter, RetrievalCorpusLoader (кэш), RetrievalRunStore.
  - `audit_middleware.py` — AuditMiddleware, логирует /api/* запросы.
  - `audit_repository.py` — PostgreSQL: audit_events, AuditRepository, make_event.
  - `answer_builder.py` — AnswerBuilder: YandexGPT synthesis по EvidenceBundle + extractive fallback + gap detection.
  - `dictionaries/` — YAML-словари:
    - `materials.yaml` — металлы, соли, реагенты, промежуточные продукты, воды, МПГ.
    - `processes.yaml` — электроэкстракция, обессоливание, RO, NF, ионный обмен, плавка, ПВП и т.д.
    - `equipment.yaml` — ванны, диафрагмы, печи, мембраны + properties + geography tokens + time_range_aliases.
- `tests/` — pytest:
  - `test_health.py` — health/meta endpoints.
  - `test_ingestion.py` — upload + task lifecycle (требует PostgreSQL).
  - `test_retrieval.py` — QueryIR + HybridRetrieval + numeric filter + access filter + /api/query.
  - `test_extractor.py` — dictionary loader + rule extractor + KnowledgeExtractor.
  - `test_query_ir.py` — QueryIRBuilder на различных типах вопросов.

### scripts/

- `seed_demo.py` — загрузка demo corpus через API, ожидание обработки.
- `e2e_smoke.py` — end-to-end smoke: один официальный вопрос через /api/query.

### demo/

- `seed_data/` — демо-корпус:
  - `obessolivanie.txt` — методы обессоливания (вопрос №1).
  - `katolit.txt` — циркуляция католита (вопрос №2).
  - `blagorodnye_metally.txt` — Au/Ag/МПГ (вопрос №3).
  - `shahtnye_vody.csv` — таблица ТЭП по шахтным водам (вопрос №4).

### ui/ (планируется)

Next.js 16, React 19, Tailwind 4, shadcn/ui. Структура будет добавлена после реализации.

### infra/ (планируется)

Зарезервировано для: docker base-images, neo4j конфиги, qdrant конфиги, postgres миграции, nginx, monitoring.

## Как поддерживать файл

- Пиши на русском.
- Описывай назначение, а не внутренние детали реализации.
- Не документируй временные артефакты, кеши, IDE-индексы и локальные данные.
- Если структура не финальная, фиксируй текущее состояние и помечай будущие зоны только после их появления в репозитории.
