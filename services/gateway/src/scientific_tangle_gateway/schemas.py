from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AccessLevel = Literal["public", "internal", "confidential", "restricted"]
UserRole = Literal["admin", "researcher", "analyst", "manager", "external_partner"]
AnalysisFlag = Literal[
    "need_table",
    "need_graph",
    "need_gaps",
    "need_conflicts",
    "need_experts",
    "need_export",
]
IngestionTaskStatus = Literal[
    "uploaded",
    "queued",
    "parsing",
    "normalized",
    "completed",
    "failed",
]


class HealthPayload(BaseModel):
    status: str = Field(pattern="^(ok|degraded)$")
    service: str
    version: str
    environment: str
    timestamp: datetime


class MetaPayload(BaseModel):
    product: str
    api_version: str
    mvp_stage: str
    contracts_status: str


class IngestionFilePayload(BaseModel):
    filename: str
    content_type: str | None
    size_bytes: int
    storage_path: str


class SourceSpanPayload(BaseModel):
    source_span_id: str
    document_id: str
    page: int | None = None
    table_id: str | None = None
    row_index: int | None = None
    column_name: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    raw_text: str
    parsed_text: str | None = None
    access_level: AccessLevel


class DocumentBlockPayload(BaseModel):
    block_id: str
    page: int | None = None
    text: str


class NormalizedDocumentPayload(BaseModel):
    document_id: str
    task_id: str
    title: str
    source_type: str
    source_path: str
    folder_category: str | None = None
    language: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    access_level: AccessLevel
    blocks: list[DocumentBlockPayload] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    source_spans: list[SourceSpanPayload] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)


class DocumentArtifactPayload(BaseModel):
    document_id: str
    task_id: str
    title: str
    source_type: str
    artifact_path: str
    source_span_count: int
    parse_warnings: list[str] = Field(default_factory=list)


class IngestionTaskPayload(BaseModel):
    task_id: str
    status: IngestionTaskStatus
    access_level: AccessLevel
    files: list[IngestionFilePayload]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)


class QueryEntityPayload(BaseModel):
    mention: str
    entity_type: str | None = None
    canonical_id: str | None = None


class QueryNumericConstraintPayload(BaseModel):
    raw_text: str
    operator: str | None = None
    min: float | None = None
    max: float | None = None
    unit: str | None = None
    dimension: str


class QueryAccessScopePayload(BaseModel):
    role: UserRole
    allowed_access_levels: list[AccessLevel]


class QueryTimeRangePayload(BaseModel):
    from_date: str | None = Field(default=None, serialization_alias="from")
    to_date: str | None = Field(default=None, serialization_alias="to")


class QueryIRPayload(BaseModel):
    query_id: str
    question: str
    goal: str
    entities: list[QueryEntityPayload] = Field(default_factory=list)
    numeric_constraints: list[QueryNumericConstraintPayload] = Field(default_factory=list)
    geo_scope: list[str] = Field(default_factory=list)
    time_range: QueryTimeRangePayload | None = None
    source_types: list[str] = Field(default_factory=list)
    access_scope: QueryAccessScopePayload
    analysis_flags: list[AnalysisFlag] = Field(default_factory=list)


class RetrievalDocumentPayload(BaseModel):
    retrieval_document_id: str
    text: str
    source_span_id: str | None = None
    document_id: str
    title: str
    source_type: str
    source_path: str
    access_level: AccessLevel
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalHitPayload(BaseModel):
    retrieval_document_id: str
    source_span_id: str | None = None
    document_id: str
    title: str
    source_type: str
    source_path: str
    access_level: AccessLevel
    text: str
    score: float
    channels: list[str] = Field(default_factory=list)


class RetrievalTraceEntryPayload(BaseModel):
    retrieval_document_id: str
    score: float


class RetrievalTracePayload(BaseModel):
    lexical: list[RetrievalTraceEntryPayload] = Field(default_factory=list)
    vector: list[RetrievalTraceEntryPayload] = Field(default_factory=list)
    fusion: list[RetrievalTraceEntryPayload] = Field(default_factory=list)


class EvidenceBundlePayload(BaseModel):
    query_id: str
    verified_claims: list[dict[str, Any]] = Field(default_factory=list)
    candidate_claims: list[dict[str, Any]] = Field(default_factory=list)
    source_spans: list[SourceSpanPayload] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    graph_subgraph: dict[str, Any] = Field(default_factory=lambda: {"nodes": [], "edges": []})
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    retrieval_trace: RetrievalTracePayload
    top_hits: list[RetrievalHitPayload] = Field(default_factory=list)


class RetrievalRunPayload(BaseModel):
    run_id: str
    query_ir: QueryIRPayload
    evidence_bundle: EvidenceBundlePayload
    created_at: datetime


class RetrievalRunRequestPayload(BaseModel):
    question: str
    role: UserRole = "researcher"
    top_k: int = Field(default=10, ge=1, le=50)


class AnswerPayload(BaseModel):
    answer_id: str
    query_id: str
    question: str
    answer_text: str
    evidence_table: list[dict[str, Any]] = Field(default_factory=list)
    source_links: list[dict[str, Any]] = Field(default_factory=list)
    confidence: str = "medium"
    warnings: list[str] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: str
    generator: str = "unknown"


class QueryRequestPayload(BaseModel):
    question: str
    role: UserRole = "researcher"
    top_k: int = Field(default=10, ge=1, le=50)


class AuditEventPayload(BaseModel):
    event_id: str
    timestamp: datetime
    user_id: str | None = None
    role: str | None = None
    action: str
    object_type: str | None = None
    object_id: str | None = None
    request_id: str | None = None
    status: str = "ok"
    detail: dict[str, Any] = Field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(UTC)
