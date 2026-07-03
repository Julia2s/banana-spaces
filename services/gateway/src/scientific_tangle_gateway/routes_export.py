from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from scientific_tangle_gateway.answer_builder import AnswerBuilder
from scientific_tangle_gateway.query_ir import QueryIRBuilder
from scientific_tangle_gateway.retrieval_engine import HybridRetrievalService
from scientific_tangle_gateway.schemas import QueryRequestPayload


def create_export_router(
    query_ir_builder: QueryIRBuilder,
    retrieval_service: HybridRetrievalService,
    answer_builder: AnswerBuilder,
) -> APIRouter:
    router = APIRouter()

    @router.post("/export/markdown", response_class=PlainTextResponse)
    async def export_markdown(request: QueryRequestPayload) -> str:
        query_ir = query_ir_builder.build(question=request.question, role=request.role)
        evidence = retrieval_service.run(
            query_id=query_ir.query_id,
            question=query_ir.question,
            allowed_access_levels=query_ir.access_scope.allowed_access_levels,
            top_k=request.top_k,
            numeric_constraints=query_ir.numeric_constraints,
        )
        answer = answer_builder.build(query_ir=query_ir, evidence=evidence)

        lines = [
            f"# Ответ на вопрос: {query_ir.question}",
            "",
            f"**Confidence:** {answer.confidence}",
            f"**Сгенерировано:** {answer.generated_at}",
            f"**Генератор:** {answer.generator}",
            "",
            "## Ответ",
            "",
            answer.answer_text,
            "",
        ]

        if answer.source_links:
            lines.append("## Источники")
            lines.append("")
            for link in answer.source_links:
                lines.append(
                    f"[{link['n']}] {link['title']} ({link['source_type']}) — score {link['score']:.3f}"
                )
            lines.append("")

        if answer.evidence_table:
            lines.append("## Таблица доказательств")
            lines.append("")
            lines.append("| N | Заголовок | Факт | Значение | Страница |")
            lines.append("|---|-----------|------|----------|----------|")
            for row in answer.evidence_table:
                lines.append(
                    f"| {row.get('n', '')} | {row.get('title', '')} | "
                    f"{row.get('fact', '')} | {row.get('value', '')} | {row.get('page', '')} |"
                )
            lines.append("")

        if answer.warnings:
            lines.append("## Предупреждения")
            lines.append("")
            for w in answer.warnings:
                lines.append(f"- {w}")
            lines.append("")

        if answer.gaps:
            lines.append("## Пробелы в знаниях")
            lines.append("")
            for g in answer.gaps:
                lines.append(f"- **{g.get('reason', '')}**: {g.get('detail', '')}")
            lines.append("")

        if answer.conflicts:
            lines.append("## Противоречия")
            lines.append("")
            for c in answer.conflicts:
                lines.append(f"- {c}")
            lines.append("")

        return "\n".join(lines)

    @router.post("/export/json")
    async def export_json(request: QueryRequestPayload) -> dict:
        query_ir = query_ir_builder.build(question=request.question, role=request.role)
        evidence = retrieval_service.run(
            query_id=query_ir.query_id,
            question=query_ir.question,
            allowed_access_levels=query_ir.access_scope.allowed_access_levels,
            top_k=request.top_k,
            numeric_constraints=query_ir.numeric_constraints,
        )
        answer = answer_builder.build(query_ir=query_ir, evidence=evidence)
        return answer.model_dump(mode="json")

    return router
