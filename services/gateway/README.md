# Gateway Service

Gateway — первый исполняемый сервис MVP. Он отвечает за внешний HTTP-контур, health/ready endpoints и будущую агрегацию API для UI.

## Текущее состояние

- `GET /health` — проверка жизни сервиса.
- `GET /ready` — готовность сервиса на уровне текущего foundation-инкремента.
- `GET /api/meta` — метаданные продукта и статус контрактов.
- `POST /api/documents/upload` — загрузка одного или нескольких исходных файлов и создание ingestion task.
- `GET /api/tasks/{task_id}` — получение статуса ingestion task.
- `POST /api/tasks/{task_id}/start` — постановка ingestion task в очередь (`queued`) для фонового worker.
- `GET /api/tasks/{task_id}/documents` — список локально сохранённых normalized artifacts.
- `GET /api/documents/{document_id}` — чтение одного `NormalizedDocument`.
- `POST /api/retrieval/run` — запуск Query IR + hybrid retrieval по вопросу.
- `GET /api/retrieval/runs/{run_id}` — чтение результата retrieval run с trace и top-k evidence.
- `GET /api/docs` — OpenAPI UI.
- `GET /api/openapi.json` — OpenAPI schema.

Загруженные исходники сохраняются в `data/raw_uploads`, normalized artifacts — в `data/normalized`. Эти локальные хранилища не входят в репозиторий. Статусы task хранятся в PostgreSQL (`ingestion_tasks`, `ingestion_files`). Фоновый worker внутри Gateway-процесса забирает задачи в статусе `queued`, выполняет MVP-нормализацию и переводит их в `completed` или `failed`. Нормализация поддерживает `txt`, `md`, `csv` и пытается извлечь текстовый слой из `pdf` через `pypdf`.

Retrieval-контур строит минимальный Query IR и запускает два канала поиска: лексический (TF-IDF-подобный) и векторный (hash embedding + cosine). Затем выполняется fusion с прозрачным `retrieval_trace`. Финальный answer synthesis на этом шаге не включён.

## Локальный запуск

```bash
python -m pip install -e services/gateway[dev]
uvicorn scientific_tangle_gateway.main:app --reload
```

## Проверка

```bash
python -m pytest services/gateway/tests
python -m ruff check services/gateway/src services/gateway/tests
```
