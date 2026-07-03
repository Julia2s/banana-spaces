from fastapi import APIRouter, HTTPException, status

from scientific_tangle_gateway.answer_builder import AnswerBuilder
from scientific_tangle_gateway.config import settings
from scientific_tangle_gateway.graph import KnowledgeGraph
from scientific_tangle_gateway.query_ir import QueryIRBuilder
from scientific_tangle_gateway.retrieval_engine import (
    HybridRetrievalService,
    RetrievalRunStore,
    generate_run_id,
)
from scientific_tangle_gateway.schemas import (
    AnswerPayload,
    QueryRequestPayload,
    RetrievalRunPayload,
    RetrievalRunRequestPayload,
    utc_now,
)


def create_retrieval_router(
    query_ir_builder: QueryIRBuilder,
    retrieval_service: HybridRetrievalService,
    run_store: RetrievalRunStore,
    answer_builder: AnswerBuilder,
    graph: KnowledgeGraph,
) -> APIRouter:
    router = APIRouter()

    @router.post("/retrieval/run", response_model=RetrievalRunPayload)
    async def run_retrieval(request: RetrievalRunRequestPayload) -> RetrievalRunPayload:
        query_ir = query_ir_builder.build(question=request.question, role=request.role)
        evidence_bundle = retrieval_service.run(
            query_id=query_ir.query_id,
            question=query_ir.question,
            allowed_access_levels=query_ir.access_scope.allowed_access_levels,
            top_k=request.top_k,
            numeric_constraints=query_ir.numeric_constraints,
        )
        run = RetrievalRunPayload(
            run_id=generate_run_id(),
            query_ir=query_ir,
            evidence_bundle=evidence_bundle,
            created_at=utc_now(),
        )
        return run_store.add(run)

    @router.get("/retrieval/runs/{run_id}", response_model=RetrievalRunPayload)
    async def get_retrieval_run(run_id: str) -> RetrievalRunPayload:
        run = run_store.get(run_id)
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Retrieval run не найден",
            )
        return run

    @router.post("/query", response_model=AnswerPayload)
    async def query(request: QueryRequestPayload) -> AnswerPayload:
        """Полный поток: QueryIR → retrieval → answer synthesis."""
        query_ir = query_ir_builder.build(question=request.question, role=request.role)
        evidence_bundle = retrieval_service.run(
            query_id=query_ir.query_id,
            question=query_ir.question,
            allowed_access_levels=query_ir.access_scope.allowed_access_levels,
            top_k=request.top_k,
            numeric_constraints=query_ir.numeric_constraints,
        )
        answer = answer_builder.build(query_ir=query_ir, evidence=evidence_bundle)
        run = RetrievalRunPayload(
            run_id=generate_run_id(),
            query_ir=query_ir,
            evidence_bundle=evidence_bundle,
            created_at=utc_now(),
        )
        run_store.add(run)
        return answer

    @router.get("/graph/evidence")
    async def graph_evidence(entity: str, limit: int = 20) -> dict:
        """Графовый поиск по сущности."""
        if not graph.available:
            return {"available": False, "evidence": [], "stats": {}}
        evidence = graph.find_evidence_by_entity(entity, limit=limit)
        return {"available": True, "evidence": evidence, "stats": graph.stats()}

    @router.get("/graph/subgraph")
    async def graph_subgraph(entity: str, max_depth: int = 2, limit: int = 30) -> dict:
        """Локальный граф для UI."""
        if not graph.available:
            return {"available": False, "nodes": [], "edges": []}
        subgraph = graph.find_related_entities(entity, max_depth=max_depth, limit=limit)
        subgraph["available"] = True
        return subgraph

    @router.get("/graph/stats")
    async def graph_stats() -> dict:
        if not graph.available:
            return {"available": False, "stats": {}}
        return {"available": True, "stats": graph.stats()}

    return router
