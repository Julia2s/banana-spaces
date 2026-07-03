from fastapi import APIRouter, Query

from scientific_tangle_gateway.audit_repository import AuditRepository
from scientific_tangle_gateway.schemas import AuditEventPayload


def create_audit_router(repository: AuditRepository) -> APIRouter:
    router = APIRouter()

    @router.get("/audit/events", response_model=list[AuditEventPayload])
    async def list_events(
        limit: int = Query(default=100, ge=1, le=1000),
        action: str | None = None,
        user_id: str | None = None,
    ) -> list[AuditEventPayload]:
        return repository.list_events(limit=limit, action_filter=action, user_filter=user_id)

    return router
