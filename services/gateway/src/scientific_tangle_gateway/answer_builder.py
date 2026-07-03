"""Answer synthesis.

Превращает EvidenceBundle в AnswerPayload через YandexGPT.
Если Yandex не настроен — fallback на тривиальную конкатенацию топ-источников.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from scientific_tangle_gateway.config import settings
from scientific_tangle_gateway.schemas import (
    AnswerPayload,
    EvidenceBundlePayload,
    QueryIRPayload,
    SourceSpanPayload,
)
from scientific_tangle_gateway.yandex_client import YandexClient

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Ты — аналитик горно-металлургических исследований.
Отвечай на вопрос пользователя строго на основе предоставленных источников.
Каждый факт в ответе сопровождай ссылкой [N], где N — номер источника.

Структура ответа:
1. Краткий вывод (1-3 предложения).
2. Развернутый ответ с разбивкой по пунктам.
3. Если есть числовые параметры — выдели их явно.
4. Если источники противоречат друг другу — отметь это.
5. Если данных недостаточно — честно скажи, чего не хватает.

Не выдумывай факты, которых нет в источниках.
Не добавляй общие рассуждения, не подкреплённые источниками.
Если в источниках нет релевантной информации — ответь: "По данному вопросу в доступных источниках информации не найдено."
"""

USER_PROMPT_TEMPLATE = """Вопрос: {question}

Источники:
{sources}

Верни ответ в формате JSON:
{{
  "answer_text": "текст ответа с [N] ссылками",
  "evidence_table": [
    {{"n": 1, "title": "...", "fact": "...", "page": "...", "value": "..."}}
  ],
  "confidence": "high|medium|low",
  "warnings": ["..."]
}}
"""


class AnswerBuilder:
    def __init__(self, client: YandexClient | None = None) -> None:
        self.client = client or YandexClient()

    def build(
        self,
        query_ir: QueryIRPayload,
        evidence: EvidenceBundlePayload,
    ) -> AnswerPayload:
        if not evidence.top_hits:
            return self._empty_answer(query_ir, evidence)

        sources_block = self._format_sources(evidence.top_hits[:5])
        user_prompt = USER_PROMPT_TEMPLATE.format(
            question=query_ir.question,
            sources=sources_block,
        )

        if self.client.is_configured:
            try:
                data = self.client.chat_json(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=0.2,
                    max_tokens=2500,
                )
                return self._to_answer_payload(data, evidence, query_ir)
            except Exception as error:
                logger.warning("LLM answer synthesis failed: %s, fallback на extractive", error)

        return self._extractive_fallback(query_ir, evidence)

    def _format_sources(self, hits: list[Any]) -> str:
        lines = []
        for i, hit in enumerate(hits, start=1):
            text = (hit.text or "")[:800].replace("\n", " ")
            lines.append(f"[{i}] {hit.title} ({hit.source_type})\n{text}")
        return "\n\n".join(lines)

    def _to_answer_payload(
        self,
        data: dict[str, Any],
        evidence: EvidenceBundlePayload,
        query_ir: QueryIRPayload,
    ) -> AnswerPayload:
        answer_text = data.get("answer_text", "")
        if not answer_text:
            return self._extractive_fallback(query_ir, evidence)

        evidence_table = data.get("evidence_table", [])
        if not isinstance(evidence_table, list):
            evidence_table = []

        confidence = data.get("confidence", "medium")
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"

        warnings = data.get("warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        warnings.extend(evidence.warnings)

        gaps = self._detect_gaps(query_ir, evidence)
        conflicts = self._detect_conflicts(evidence)

        return AnswerPayload(
            answer_id=str(uuid4()),
            query_id=query_ir.query_id,
            question=query_ir.question,
            answer_text=answer_text,
            evidence_table=evidence_table,
            source_links=[
                {
                    "n": i + 1,
                    "source_span_id": hit.source_span_id,
                    "document_id": hit.document_id,
                    "title": hit.title,
                    "source_type": hit.source_type,
                    "score": hit.score,
                    "channels": hit.channels,
                }
                for i, hit in enumerate(evidence.top_hits[:5])
            ],
            confidence=confidence,
            warnings=warnings,
            gaps=gaps,
            conflicts=conflicts,
            generated_at=datetime.now(UTC).isoformat(),
            generator="yandexgpt" if self.client.is_configured else "extractive",
        )

    def _extractive_fallback(
        self,
        query_ir: QueryIRPayload,
        evidence: EvidenceBundlePayload,
    ) -> AnswerPayload:
        if not evidence.top_hits:
            return self._empty_answer(query_ir, evidence)

        parts = []
        for i, hit in enumerate(evidence.top_hits[:3], start=1):
            text = (hit.text or "")[:300].replace("\n", " ")
            parts.append(f"[{i}] {hit.title}: {text}")

        answer_text = "По данным доступных источников:\n\n" + "\n\n".join(parts)
        warnings = ["LLM не настроен — ответ сформирован как extractive summary"]
        warnings.extend(evidence.warnings)

        return AnswerPayload(
            answer_id=str(uuid4()),
            query_id=query_ir.query_ir_id if hasattr(query_ir, "query_ir_id") else query_ir.query_id,
            question=query_ir.question,
            answer_text=answer_text,
            evidence_table=[],
            source_links=[
                {
                    "n": i + 1,
                    "source_span_id": hit.source_span_id,
                    "document_id": hit.document_id,
                    "title": hit.title,
                    "source_type": hit.source_type,
                    "score": hit.score,
                    "channels": hit.channels,
                }
                for i, hit in enumerate(evidence.top_hits[:5])
            ],
            confidence="low",
            warnings=warnings,
            gaps=self._detect_gaps(query_ir, evidence),
            conflicts=self._detect_conflicts(evidence),
            generated_at=datetime.now(UTC).isoformat(),
            generator="extractive",
        )

    def _empty_answer(
        self,
        query_ir: QueryIRPayload,
        evidence: EvidenceBundlePayload,
    ) -> AnswerPayload:
        return AnswerPayload(
            answer_id=str(uuid4()),
            query_id=query_ir.query_id,
            question=query_ir.question,
            answer_text="По данному вопросу в доступных источниках информации не найдено.",
            evidence_table=[],
            source_links=[],
            confidence="low",
            warnings=evidence.warnings + ["Нет релевантных источников"],
            gaps=[{"reason": "no_evidence", "detail": query_ir.question}],
            conflicts=[],
            generated_at=datetime.now(UTC).isoformat(),
            generator="none",
        )

    def _detect_gaps(self, query_ir: QueryIRPayload, evidence: EvidenceBundlePayload) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []
        if not evidence.top_hits:
            gaps.append({"reason": "no_evidence", "detail": "Релевантные источники не найдены"})
        if query_ir.geo_scope and not any(
            "росс" in (hit.text or "").lower() or "russia" in (hit.text or "").lower()
            for hit in evidence.top_hits
        ):
            if "россия" in query_ir.geo_scope or "рф" in query_ir.geo_scope:
                gaps.append({
                    "reason": "geo_gap",
                    "detail": "Не найдены источники с явной российской географией по теме запроса",
                })
        if query_ir.time_range and not any(
            "2021" in (hit.text or "") or "2022" in (hit.text or "") or "2023" in (hit.text or "")
            or "2024" in (hit.text or "")
            for hit in evidence.top_hits
        ):
            gaps.append({
                "reason": "time_gap",
                "detail": "Не найдены источники за последние 5 лет",
            })
        return gaps

    def _detect_conflicts(self, evidence: EvidenceBundlePayload) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        if len(evidence.top_hits) < 2:
            return conflicts
        return conflicts
