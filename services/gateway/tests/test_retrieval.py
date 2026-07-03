import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scientific_tangle_gateway.answer_builder import AnswerBuilder
from scientific_tangle_gateway.embeddings import EmbeddingsProvider
from scientific_tangle_gateway.graph import KnowledgeGraph
from scientific_tangle_gateway.query_ir import QueryIRBuilder
from scientific_tangle_gateway.retrieval_engine import (
    HybridRetrievalService,
    LexicalRetriever,
    RetrievalCorpusLoader,
    RetrievalRunStore,
    TableRetriever,
    VectorRetriever,
)
from scientific_tangle_gateway.routes_retrieval import create_retrieval_router


def _write_normalized_artifact(
    path: Path,
    document_id: str,
    title: str,
    text: str,
    access_level: str,
) -> None:
    payload = {
        "document_id": document_id,
        "task_id": "task-test",
        "title": title,
        "source_type": "txt",
        "source_path": str(path),
        "folder_category": "test",
        "language": "ru",
        "metadata": {},
        "access_level": access_level,
        "blocks": [
            {
                "block_id": f"{document_id}:block:1",
                "text": text,
                "page": None,
            }
        ],
        "tables": [],
        "source_spans": [
            {
                "source_span_id": f"{document_id}:span:1",
                "document_id": document_id,
                "raw_text": text,
                "parsed_text": text,
                "access_level": access_level,
                "page": None,
                "table_id": None,
                "row_index": None,
                "column_name": None,
                "char_start": 0,
                "char_end": len(text),
            }
        ],
        "parse_warnings": [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _build_retrieval_service(normalized_dir: Path) -> HybridRetrievalService:
    return HybridRetrievalService(
        corpus_loader=RetrievalCorpusLoader(
            normalized_dir=normalized_dir,
            source_corpus_dir=normalized_dir / "empty-source",
            source_char_limit=8000,
        ),
        lexical_retriever=LexicalRetriever(),
        vector_retriever=VectorRetriever(embeddings=EmbeddingsProvider()),
        table_retriever=TableRetriever(),
    )


def test_query_ir_builder_extracts_numeric_and_flags() -> None:
    builder = QueryIRBuilder()
    query_ir = builder.build(
        question="Какие методы обессоливания при 200 мг/л и таблица по России?",
        role="researcher",
    )

    assert query_ir.goal
    assert query_ir.numeric_constraints
    assert any(c.unit in {"мг/л"} for c in query_ir.numeric_constraints)
    assert "need_table" in query_ir.analysis_flags
    assert "россия" in query_ir.geo_scope
    assert query_ir.access_scope.allowed_access_levels


def test_query_ir_builder_extracts_time_range() -> None:
    builder = QueryIRBuilder()
    query_ir = builder.build(
        question="Покажи эксперименты за последние 5 лет",
        role="researcher",
    )
    assert query_ir.time_range is not None
    assert query_ir.time_range.from_date == "2021-01-01"


def test_hybrid_retrieval_returns_top_k_and_trace(tmp_path: Path) -> None:
    task_dir = tmp_path / "task-1"
    task_dir.mkdir(parents=True)
    _write_normalized_artifact(
        path=task_dir / "doc-a.json",
        document_id="doc-a",
        title="Обессоливание воды",
        text="Методы обессоливания воды и показатели качества.",
        access_level="public",
    )
    _write_normalized_artifact(
        path=task_dir / "doc-b.json",
        document_id="doc-b",
        title="Католит",
        text="Циркуляция католита при электроэкстракции никеля.",
        access_level="public",
    )

    service = _build_retrieval_service(tmp_path)
    evidence = service.run(
        query_id="query-1",
        question="обессоливание воды",
        allowed_access_levels=["public"],
        top_k=3,
    )

    assert evidence.top_hits
    assert evidence.retrieval_trace.lexical
    assert evidence.retrieval_trace.fusion
    top_titles = {hit.title for hit in evidence.top_hits}
    assert "Обессоливание воды" in top_titles


def test_access_filtering_blocks_restricted_documents(tmp_path: Path) -> None:
    task_dir = tmp_path / "task-1"
    task_dir.mkdir(parents=True)
    _write_normalized_artifact(
        path=task_dir / "doc-public.json",
        document_id="doc-public",
        title="Публичный источник",
        text="Данные по обессоливанию.",
        access_level="public",
    )
    _write_normalized_artifact(
        path=task_dir / "doc-confidential.json",
        document_id="doc-confidential",
        title="Закрытый источник",
        text="Секретные данные по обессоливанию.",
        access_level="confidential",
    )

    service = _build_retrieval_service(tmp_path)
    evidence = service.run(
        query_id="query-2",
        question="обессоливание",
        allowed_access_levels=["public"],
        top_k=5,
    )

    assert evidence.top_hits
    assert all(hit.access_level == "public" for hit in evidence.top_hits)


def test_numeric_constraint_filters_results(tmp_path: Path) -> None:
    task_dir = tmp_path / "task-1"
    task_dir.mkdir(parents=True)
    _write_normalized_artifact(
        path=task_dir / "doc-low.json",
        document_id="doc-low",
        title="Низкая концентрация",
        text="Концентрация сульфатов составляет 100 мг/л.",
        access_level="public",
    )
    _write_normalized_artifact(
        path=task_dir / "doc-high.json",
        document_id="doc-high",
        title="Высокая концентрация",
        text="Концентрация сульфатов составляет 5000 мг/л.",
        access_level="public",
    )

    from scientific_tangle_gateway.schemas import QueryNumericConstraintPayload

    constraint = QueryNumericConstraintPayload(
        raw_text="200 мг/л",
        operator="<=",
        min=None,
        max=200.0,
        unit="мг/л",
        dimension="concentration",
    )

    service = _build_retrieval_service(tmp_path)
    evidence = service.run(
        query_id="query-3",
        question="сульфаты",
        allowed_access_levels=["public"],
        top_k=5,
        numeric_constraints=[constraint],
    )

    titles = {hit.title for hit in evidence.top_hits}
    assert "Низкая концентрация" in titles
    assert "Высокая концентрация" not in titles


def test_query_api_returns_answer(tmp_path: Path) -> None:
    task_dir = tmp_path / "task-1"
    task_dir.mkdir(parents=True)
    _write_normalized_artifact(
        path=task_dir / "doc-a.json",
        document_id="doc-a",
        title="Обессоливание",
        text="Методы обессоливания воды на фабрике: обратный осмос, нанофильтрация, ионный обмен.",
        access_level="public",
    )

    app = FastAPI()
    app.include_router(
        create_retrieval_router(
            query_ir_builder=QueryIRBuilder(),
            retrieval_service=_build_retrieval_service(tmp_path),
            run_store=RetrievalRunStore(),
            answer_builder=AnswerBuilder(),
            graph=KnowledgeGraph(uri="bolt://nonexistent:7687"),
        ),
        prefix="/api",
    )

    client = TestClient(app)
    response = client.post(
        "/api/query",
        json={"question": "методы обессоливания воды", "role": "researcher", "top_k": 5},
    )

    assert response.status_code == 200
    answer = response.json()
    assert answer["question"]
    assert answer["answer_text"]
    assert answer["source_links"]
    assert answer["confidence"] in {"high", "medium", "low"}
