# ScientificTangle — короткий рабочий план

Версия: 2.0. Дата: 2025-07-03. Дедлайн: 2025-07-04 23:59.

Этот документ — **единственный источник истины** для команды на ближайшие 36 часов.
Полное ТЗ лежит в `docs/nauchny_klubok_top1_tz.md` (596 строк, историческая справка).
Если что-то здесь противоречит полному ТЗ — приоритет за этим документом.

## 1. Что мы строим

**Доказуемую карту знаний для горно-металлургических R&D.**

Пользователь загружает PDF/XLSX/CSV → система извлекает факты с привязкой к источнику →
записывает в граф (Neo4j) + векторное хранилище (Qdrant) → отвечает на вопросы на
естественном языке с **обязательной ссылкой на конкретный фрагмент источника**.

Каждый факт в ответе = `[N]` ссылка на SourceSpan (документ, страница, при наличии — строка/колонка таблицы).

## 2. Три отличия от других команд

Чтобы жюри не увидело «два одинаковых решения»:

1. **YandexGPT 4 Pro через AI Studio** — как ядро для extraction и answer synthesis.
   Доменное преимущество: русский технический контекст (католит, штейн, ПВП, МПГ).
2. **Table-first** — таблицы (XLSX/CSV) как граждане первого класса.
   Каждая ячейка = SourceSpan с row/column. В ответе — конкретная ячейка, не абзац.
3. **Evidence Card UI** — не чат, а карточка доказательств:
   вывод + нумерованные источники + числовые факты + пробелы.

## 3. Архитектура (модульный монолит)

Один сервис `gateway` (FastAPI), разделённый на модули с чёткими границами.

```
services/gateway/src/scientific_tangle_gateway/
  main.py              ← точка сборки FastAPI
  config.py            ← настройки из .env
  schemas.py           ← Pydantic DTO (контракты для UI)
  routes_ingestion.py  ← /api/documents/*, /api/tasks/*
  routes_retrieval.py  ← /api/retrieval/*, /api/query/*
  routes_audit.py      ← /api/audit/* (новое)
  routes_export.py     ← /api/export/* (новое)

  # Модуль INGESTION (Бэкендер A)
  ingestion.py         ← lifecycle: uploaded→queued→parsing→normalized→extracted→completed
  normalization.py     ← PDF/XLSX/DOCX/CSV → NormalizedDocument + SourceSpan
  task_repository.py   ← PostgreSQL: ingestion_tasks, ingestion_files
  task_worker.py       ← фоновый worker, orchestrates extraction/graph/indexing

  # Модуль KNOWLEDGE (Бэкендер B)
  yandex_client.py     ← обёртка над YandexGPT (folder_id + IAM token из .env)
  extractor.py         ← LLM + rule-based извлечение сущностей/чисел/связей
  graph.py             ← Neo4j adapter: write/query сущностей, claims, evidence
  claims.py            ← Claim builder, versioning, conflict marking
  dictionaries/        ← YAML: materials.yaml, processes.yaml, equipment.yaml

  # Модуль RETRIEVAL (Бэкендер A + B)
  query_ir.py          ← парсинг вопроса → QueryIR (entities, constraints, geo, time)
  retrieval_engine.py  ← HybridRetrieval: lexical + vector + table + graph
  table_retriever.py   ← поиск по строкам таблиц с числовым фильтром
  graph_retriever.py   ← Cypher-запросы по entity linking

  # Модуль SYNTHESIS (Бэкендер B)
  answer_builder.py    ← YandexGPT: EvidenceBundle → AnswerPayload
  gaps.py              ← выявление пробелов в знаниях
  conflicts.py         ← попарное сравнение claims

  # Модуль AUDIT (SRE)
  audit_middleware.py  ← FastAPI middleware: логирует все /api/* запросы
  audit_repository.py  ← PostgreSQL: audit_events

ui/                    ← Next.js 16, React 19, Tailwind, shadcn/ui (Фронтендер)
demo/seed_data/        ← 5-10 PDF/XLSX для демо (SRE/Lead)
scripts/seed_demo.py   ← загрузка seed corpus через API
scripts/e2e_smoke.py   ← один официальный вопрос end-to-end
```

## 4. Роли и зоны ответственности

| Человек | Модуль | Что делает | Что сдаёт |
|---|---|---|---|
| **Бэкендер A** | INGESTION + RETRIEVAL | normalizer (XLSX/DOCX), table_retriever, real vector retriever, numeric filter | рабочие эндпоинты `/api/documents/upload`, `/api/retrieval/run` |
| **Бэкендер B** | KNOWLEDGE + SYNTHESIS | yandex_client, extractor, graph (Neo4j), answer_builder | `extraction` шаг в worker, `/api/query` с LLM-ответом |
| **Фронтендер** | UI | Next.js: Upload + Query + SourceViewer + EvidenceCard | `ui/` запускается через `npm run dev`, общается с gateway |
| **SRE / Lead** | INFRA + DEMO | docker-compose, audit, seed_data, e2e_smoke, видео, презентация | `make up` поднимает всё, `make seed` загружает корпус, deploy-ссылка |

Если вас **трое** — SRE-зоны берёт на себя Lead (тот, кто лучше знает Docker).
Если **четверо** — добавляется отдельный ML-инженер на extractor+answer_builder.

## 5. Контракты (заморожены после Sync 1)

Все DTO в `shared/contracts/*.json` и `schemas.py`. **Менять только через общий decision.**

Ключевые контракты:
- `NormalizedDocument` — результат парсинга файла
- `SourceSpan` — фрагмент источника (page, row, column, char_start/end)
- `QueryIR` — типизированный план запроса
- `EvidenceBundle` — набор доказательств из retrieval
- `AnswerPayload` — финальный ответ для UI

UI работает по `AnswerPayload` — даже если backend ещё не готов, фронт может
использовать mock из `ui/mock/answer_payload_mock.json`.

## 6. План по времени (36 часов)

| Час | Что | Кто |
|---|---|---|
| 0–2 | Все поднимают `make up`, читают PLAN_SHORT, делят модули | Все |
| 2–4 | Заморозка контрактов, mock-ответ для UI | Lead + Фронт |
| 2–8 | Backend: normalizer (XLSX/DOCX), table_retriever, vector retriever | Бэк A |
| 2–8 | Backend: yandex_client, extractor, graph Neo4j, answer_builder | Бэк B |
| 2–8 | Frontend: Upload + Query + SourceViewer по mock | Фронт |
| 4–6 | SRE: seed_data (5-10 файлов), audit_middleware, e2e_smoke | SRE |
| 8–14 | **Sync: end-to-end на одном официальном вопросе** (католит или обессоливание) | Все |
| 14–20 | Второй официальный вопрос, export Markdown, conflicts/gaps | Бэк A+B |
| 14–20 | Frontend: EvidenceCard, LocalGraph, Audit page | Фронт |
| 20–28 | Тесты, видеодемо (5 мин), презентация (8-10 слайдов) | Все |
| 28–36 | Deploy, архив, финальные ссылки, backup | Lead |

## 7. MVP-отсечка (обязательный минимум для сдачи)

MVP готов, когда **проходит один официальный вопрос end-to-end**:

1. `make up` поднимает весь стек (gateway, postgres, neo4j, qdrant, redis, minio).
2. `make seed` загружает 5-10 файлов из `demo/seed_data/`.
3. В UI пользователь задаёт вопрос (например, про католит).
4. Система возвращает ответ с **минимум 2 ссылками на источники**.
5. Клик по ссылке открывает SourceSpan с подсветкой.
6. Audit log фиксирует запрос.
7. `make e2e` проходит с exit code 0.

**Всё остальное (4 вопроса, dashboards, notifications, PDF export) — top-1, не успеем.**

## 8. Что НЕ делать

- ❌ 9 микросервисов — один модульный монолит.
- ❌ OWL/RDF/SHACL — операционная онтология в YAML.
- ❌ OCR, анализ картинок — только текстовый слой.
- ❌ Свободный Cypher от LLM — только QueryIR → типизированные запросы.
- ❌ Реальная авторизация — role switcher в UI, честно помеченный mock.
- ❌ Хардкод ответов на официальные вопросы.
- ❌ Любой факт без source_span_id.

## 9. Технологический стек

- **Backend**: Python 3.12, FastAPI 0.116+, Pydantic 2, psycopg 3, pypdf, openpyxl, python-docx
- **Embeddings**: `sentence-transformers/LaBSE` (мультиязычный, локально, без API) — ставится через pip
- **LLM**: YandexGPT 4 Pro через AI Studio REST API (folder_id + IAM token из .env)
- **Graph**: Neo4j 5 community
- **Vector**: Qdrant 1.15
- **DB**: PostgreSQL 16
- **Queue**: пока PostgreSQL + asyncio polling (Redis на будущее)
- **UI**: Next.js 16, React 19, Tailwind 4, shadcn/ui
- **Deploy**: локальный docker compose + видео (облако если успеем)

## 10. Переменные окружения

`.env` (не коммитить, есть `.env.example`):

```
# YandexGPT
YANDEX_FOLDER_ID=<ваш_folder_id>
YANDEX_IAM_TOKEN=<ваш_iam_token>
YANDEXGPT_MODEL=yandexgpt-4-pro
YANDEX_EMBEDDINGS_MODEL=emb:text-search-doc

# Gateway
GATEWAY_ENVIRONMENT=local
GATEWAY_DB_DSN=postgresql://scientific_tangle:scientific_tangle@localhost:5432/scientific_tangle
GATEWAY_NEO4J_URI=bolt://localhost:7687
GATEWAY_NEO4J_USER=neo4j
GATEWAY_NEO4J_PASSWORD=scientific_tangle
GATEWAY_QDRANT_URL=http://localhost:6333
GATEWAY_RAW_UPLOAD_DIR=data/raw_uploads
GATEWAY_NORMALIZED_DIR=data/normalized
GATEWAY_SOURCE_CORPUS_DIR=demo/seed_data

# Infra
POSTGRES_DB=scientific_tangle
POSTGRES_USER=scientific_tangle
POSTGRES_PASSWORD=scientific_tangle
NEO4J_AUTH=neo4j/scientific_tangle
```

**API-ключи не коммитить.** Каждый разработчик создаёт `.env` локально из `.env.example`.

## 11. Команды разработки

```bash
make up              # поднять docker-compose
make down            # остановить
make logs            # логи всех сервисов
make gateway-install # установить gateway в dev-режиме
make gateway-test    # pytest
make gateway-lint    # ruff
make seed            # загрузить demo/seed_data через API
make e2e             # один официальный вопрос end-to-end
make reset-demo      # удалить volumes и данные
```

## 12. Официальные вопросы (приоритет порядка)

1. **Католит** — технические решения циркуляции католита при электроэкстракции никеля, оптимальная скорость потока. (Самый простой — есть в стандартных статьях.)
2. **Обессоливание** — методы для обогатительной фабрики, сульфаты 200-300 мг/л, сухой остаток ≤1000 мг/дм³. (Сложнее — числовой фильтр.)
3. **Au/Ag/МПГ** — эксперименты и публикации за последние 5 лет по распределению между штейном и шлаком. (Временной фильтр.)
4. **Шахтные воды** — закачка в глубокие горизонты, отечественная vs зарубежная практика, ТЭП. (География.)

**MVP = вопрос 1 ИЛИ вопрос 2 end-to-end.** Остальное — если успеем.

## 13. Риски и fallback

| Риск | Fallback |
|---|---|
| YandexGPT API недоступен | Mock-ответы в `synthesis/mock_answers.json`, честная плашка «demo mode» |
| Neo4j не поднимается | Graph-retriever возвращает пустой EvidenceBundle, ответ только из lexical+vector |
| PDF без текстового слоя | parse_warning, документ индексируется с пометкой «no text layer» |
| 3-5 секунд не выдерживаются | Кэш QueryIR, top_k=5, precomputed embeddings в Qdrant |
| Команда не успевает | MVP-отсечка: один вопрос end-to-end, остальное вырезаем |

## 14. Сдача

К 23:59 4 июля:

1. GitHub-репозиторий с кодом
2. Яндекс.Диск: архив кода + видео-демо (≤5 мин)
3. Презентация .pptx или .pdf (8-10 слайдов)
4. (Опционально) Deploy-ссылка для жюри

Видео-сценарий (5 минут):
- 0:00–0:30 — проблема
- 0:30–1:30 — загрузка corpus через UI, ingestion report
- 1:30–2:30 — вопрос про католит, ответ, открытие SourceSpan
- 2:30–3:30 — второй вопрос (обессоливание с числовым фильтром)
- 3:30–4:30 — локальный граф, переход к эксперту
- 4:30–5:00 — итоги: Neo4j + Qdrant + YandexGPT

## 15. Definition of Done для каждого модуля

- **INGESTION**: `POST /api/documents/upload` принимает PDF/XLSX/CSV/DOCX, возвращает task_id; worker доводит до `completed` с записью в Neo4j и Qdrant.
- **KNOWLEDGE**: после ingestion в Neo4j есть `(:Document)-[:HAS_SPAN]->(:SourceSpan)-[:MENTIONS]->(:Entity)`, в Qdrant — embeddings чанков.
- **RETRIEVAL**: `POST /api/retrieval/run` возвращает EvidenceBundle с top_hits из 3 каналов (lexical/vector/table) + trace.
- **SYNTHESIS**: `POST /api/query` возвращает AnswerPayload с `answer_text`, `evidence_table`, `confidence`, `source_links`.
- **UI**: можно загрузить файл, задать вопрос, увидеть ответ с источниками, открыть SourceSpan.
- **AUDIT**: каждый запрос к `/api/*` записан в `audit_events` таблицу.
- **SRE**: `make up` + `make seed` + `make e2e` работают на чистой машине.
