"""Audit middleware.

Логирует все запросы к /api/* в PostgreSQL audit_events.
Не блокирует запрос — пишет асинхронно после возврата ответа.
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from scientific_tangle_gateway.audit_repository import AuditRepository, make_event

logger = logging.getLogger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, repository: AuditRepository, enabled: bool = True) -> None:
        super().__init__(app)
        self.repository = repository
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.enabled or not request.url.path.startswith("/api/"):
            return await call_next(request)

        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id

        start_time = time.monotonic()
        status = "ok"
        try:
            response = await call_next(request)
            if response.status_code >= 400:
                status = "error"
            response.headers["x-request-id"] = request_id
            return response
        except Exception:
            status = "error"
            raise
        finally:
            duration_ms = (time.monotonic() - start_time) * 1000
            try:
                action = self._derive_action(request.method, request.url.path)
                if action:
                    event = make_event(
                        action=action,
                        request_id=request_id,
                        status=status,
                        detail={
                            "method": request.method,
                            "path": request.url.path,
                            "duration_ms": round(duration_ms, 2),
                            "status_code": response.status_code if "response" in locals() else None,
                        },
                    )
                    self.repository.write(event)
            except Exception as error:
                logger.warning("Audit write failed: %s", error)

    @staticmethod
    def _derive_action(method: str, path: str) -> str | None:
        if path.startswith("/api/documents/upload"):
            return "document_uploaded"
        if path.startswith("/api/tasks/"):
            return "task_accessed"
        if path.startswith("/api/retrieval/run"):
            return "query_created"
        if path.startswith("/api/retrieval/runs/"):
            return "retrieval_accessed"
        if path.startswith("/api/query"):
            return "answer_generated"
        if path.startswith("/api/source"):
            return "source_opened"
        if path.startswith("/api/audit"):
            return "audit_accessed"
        if path.startswith("/api/export"):
            return "document_exported"
        if path.startswith("/api/graph"):
            return "graph_accessed"
        if path.startswith("/api/search"):
            return "search_executed"
        return None
