"""Claim builder.

Превращает ExtractionResult в объекты Claim, готовые для записи в Neo4j.
Управляет статусами: extracted → candidate → auto_verified → verified | conflicting | deprecated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from scientific_tangle_gateway.extractor import ExtractedClaim, ExtractionResult

logger = logging.getLogger(__name__)


@dataclass
class BuiltClaim:
    claim_id: str
    text: str
    source_span_id: str
    entities: list[str]
    quantities: list[dict[str, Any]]
    status: str
    confidence: float
    extractor: str
    extracted_at: str


def build_claims(
    extraction: ExtractionResult,
    existing_claims: list[dict[str, Any]] | None = None,
) -> list[BuiltClaim]:
    """Превращает извлечённые claims в BuiltClaim с статусом и метаданными."""
    built: list[BuiltClaim] = []
    existing = existing_claims or []

    for extracted in extraction.claims:
        status = _determine_status(extracted, existing)
        entities = sorted(set(extracted.entities))
        quantities = [
            {
                "raw_text": q.raw_text,
                "value": q.value,
                "operator": q.operator,
                "unit": q.unit,
                "dimension": q.dimension,
                "property_name": q.property_name,
            }
            for q in extraction.quantities
        ]
        built.append(
            BuiltClaim(
                claim_id=extracted.claim_id,
                text=extracted.text,
                source_span_id=extracted.source_span_id,
                entities=entities,
                quantities=quantities,
                status=status,
                confidence=extracted.confidence,
                extractor=extracted.extractor,
                extracted_at=datetime.now(UTC).isoformat(),
            )
        )
    return built


def _determine_status(
    extracted: ExtractedClaim,
    existing: list[dict[str, Any]],
) -> str:
    """Определяет статус claim на основе confidence и существующих claims."""
    if extracted.status == "candidate":
        return "candidate"
    if extracted.confidence >= 0.85:
        return "auto_verified"
    if extracted.confidence >= 0.6:
        return "extracted"
    return "candidate"


def detect_conflicts(
    new_claim: BuiltClaim,
    existing_claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Простое правило: если новый claim и существующий имеют пересечение по entities,
    но разные числовые значения одного и того же свойства — это конфликт.
    """
    conflicts: list[dict[str, Any]] = []
    new_entities = set(new_claim.entities)
    new_props = {q["property_name"]: q["value"] for q in new_claim.quantities if q["property_name"]}

    for existing in existing_claims:
        ex_entities = set(existing.get("entities", []))
        if not new_entities & ex_entities:
            continue
        ex_props = {q.get("property_name"): q.get("value") for q in existing.get("quantities", []) if q.get("property_name")}
        for prop, value in new_props.items():
            if prop in ex_props and ex_props[prop] is not None and ex_props[prop] != value:
                conflicts.append({
                    "property": prop,
                    "new_value": value,
                    "existing_value": ex_props[prop],
                    "new_claim_id": new_claim.claim_id,
                    "existing_claim_id": existing.get("claim_id"),
                })
    return conflicts


def make_claim_id(source_span_id: str, text: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{source_span_id}:{text}"))
