from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scientific_tangle_gateway.answer_builder import AnswerBuilder
from scientific_tangle_gateway.audit_middleware import AuditMiddleware
from scientific_tangle_gateway.audit_repository import AuditRepository
from scientific_tangle_gateway.config import settings
from scientific_tangle_gateway.extractor import KnowledgeExtractor
from scientific_tangle_gateway.graph import KnowledgeGraph
from scientific_tangle_gateway.ingestion import LocalUploadStorage
from scientific_tangle_gateway.normalization import (
    DocumentNormalizer,
    LocalNormalizedDocumentStore,
)
from scientific_tangle_gateway.query_ir import QueryIRBuilder
from scientific_tangle_gateway.retrieval_engine import (
    HybridRetrievalService,
    LexicalRetriever,
    RetrievalCorpusLoader,
    RetrievalRunStore,
    TableRetriever,
    VectorRetriever,
)
from scientific_tangle_gateway.embeddings import EmbeddingsProvider
from scientific_tangle_gateway.routes_audit import create_audit_router
from scientific_tangle_gateway.routes_export import create_export_router
from scientific_tangle_gateway.routes_ingestion import create_ingestion_router
from scientific_tangle_gateway.routes_retrieval import create_retrieval_router
from scientific_tangle_gateway.schemas import HealthPayload, MetaPayload, utc_now
from scientific_tangle_gateway.task_repository import TaskRepository
from scientific_tangle_gateway.task_worker import IngestionTaskWorker

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def build_health_payload() -> HealthPayload:
    return HealthPayload(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        timestamp=utc_now(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    repository = app.state.task_repository
    audit_repository = app.state.audit_repository
    worker = app.state.task_worker

    repository.init_db()
    audit_repository.init_db()
    await worker.start()
    yield
    await worker.stop()


def create_app() -> FastAPI:
    repository = TaskRepository(settings.db_dsn)
    audit_repository = AuditRepository(settings.db_dsn)
    normalizer = DocumentNormalizer()
    document_store = LocalNormalizedDocumentStore(settings.normalized_dir)
    embeddings = EmbeddingsProvider()
    graph = KnowledgeGraph()

    retrieval_service = HybridRetrievalService(
        corpus_loader=RetrievalCorpusLoader(
            normalized_dir=settings.normalized_dir,
            source_corpus_dir=settings.source_corpus_dir,
            source_char_limit=settings.retrieval_source_char_limit,
        ),
        lexical_retriever=LexicalRetriever(),
        vector_retriever=VectorRetriever(embeddings=embeddings),
        table_retriever=TableRetriever(),
    )
    query_ir_builder = QueryIRBuilder()
    retrieval_run_store = RetrievalRunStore()
    answer_builder = AnswerBuilder()
    extractor = KnowledgeExtractor()
    worker = IngestionTaskWorker(
        repository=repository,
        normalizer=normalizer,
        document_store=document_store,
        extractor=extractor,
        graph=graph,
        poll_interval_seconds=settings.worker_poll_interval_seconds,
        batch_size=settings.worker_batch_size,
    )

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url=f"{settings.api_prefix}/docs",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        AuditMiddleware,
        repository=audit_repository,
        enabled=settings.audit_enabled,
    )

    app.state.task_repository = repository
    app.state.audit_repository = audit_repository
    app.state.task_worker = worker
    app.state.graph = graph
    app.state.retrieval_run_store = retrieval_run_store

    app.include_router(
        create_ingestion_router(
            repository=repository,
            storage=LocalUploadStorage(settings.raw_upload_dir),
            document_store=document_store,
        ),
        prefix=settings.api_prefix,
        tags=["ingestion"],
    )
    app.include_router(
        create_retrieval_router(
            query_ir_builder=query_ir_builder,
            retrieval_service=retrieval_service,
            run_store=retrieval_run_store,
            answer_builder=answer_builder,
            graph=graph,
        ),
        prefix=settings.api_prefix,
        tags=["retrieval"],
    )
    app.include_router(
        create_audit_router(repository=audit_repository),
        prefix=settings.api_prefix,
        tags=["audit"],
    )
    app.include_router(
        create_export_router(
            query_ir_builder=query_ir_builder,
            retrieval_service=retrieval_service,
            answer_builder=answer_builder,
        ),
        prefix=settings.api_prefix,
        tags=["export"],
    )

    @app.get("/health", response_model=HealthPayload)
    async def health() -> HealthPayload:
        return build_health_payload()

    @app.get("/ready", response_model=HealthPayload)
    async def ready() -> HealthPayload:
        return build_health_payload()

    @app.get(f"{settings.api_prefix}/meta", response_model=MetaPayload)
    async def meta() -> MetaPayload:
        graph_available = graph.available
        return MetaPayload(
            product="ScientificTangle",
            api_version=settings.app_version,
            mvp_stage="extraction" if graph_available else "ingestion",
            contracts_status="draft",
        )

    @app.get(f"{settings.api_prefix}/health/detail")
    async def health_detail() -> dict:
        return {
            "service": "ok",
            "neo4j_available": graph.available,
            "neo4j_stats": graph.stats() if graph.available else {},
            "embeddings_backend": embeddings.backend,
            "yandex_configured": bool(settings.yandex_folder_id and settings.yandex_iam_token),
        }

    return app


app = create_app()
