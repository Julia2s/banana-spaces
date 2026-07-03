"""Audit log repository.

PostgreSQL-таблица audit_events для логирования всех действий пользователей.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from uuid import uuid4

import psycopg

from scientific_tangle_gateway.schemas import AuditEventPayload

logger = logging.getLogger(__name__)


class AuditRepository:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def init_db(self) -> None:
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL,
                    user_id TEXT NULL,
                    role TEXT NULL,
                    action TEXT NOT NULL,
                    object_type TEXT NULL,
                    object_id TEXT NULL,
                    request_id TEXT NULL,
                    status TEXT NOT NULL DEFAULT 'ok',
                    detail_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS audit_events_timestamp_idx ON audit_events (timestamp DESC)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS audit_events_action_idx ON audit_events (action)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS audit_events_user_idx ON audit_events (user_id)"
            )
            conn.commit()

    def write(self, event: AuditEventPayload) -> AuditEventPayload:
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_events (
                    event_id, timestamp, user_id, role, action,
                    object_type, object_id, request_id, status, detail_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event.event_id,
                    event.timestamp,
                    event.user_id,
                    event.role,
                    event.action,
                    event.object_type,
                    event.object_id,
                    event.request_id,
                    event.status,
                    json.dumps(event.detail, ensure_ascii=False),
                ),
            )
            conn.commit()
        return event

    def list_events(
        self,
        limit: int = 100,
        action_filter: str | None = None,
        user_filter: str | None = None,
    ) -> list[AuditEventPayload]:
        query = "SELECT event_id, timestamp, user_id, role, action, object_type, object_id, request_id, status, detail_json FROM audit_events"
        conditions = []
        params: list = []
        if action_filter:
            conditions.append("action = %s")
            params.append(action_filter)
        if user_filter:
            conditions.append("user_id = %s")
            params.append(user_filter)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)

        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._to_payload(row) for row in rows]

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn)

    @staticmethod
    def _to_payload(row: tuple) -> AuditEventPayload:
        return AuditEventPayload(
            event_id=row[0],
            timestamp=row[1],
            user_id=row[2],
            role=row[3],
            action=row[4],
            object_type=row[5],
            object_id=row[6],
            request_id=row[7],
            status=row[8],
            detail=json.loads(row[9]) if row[9] else {},
        )


def make_event(
    action: str,
    *,
    user_id: str | None = None,
    role: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    request_id: str | None = None,
    status: str = "ok",
    detail: dict | None = None,
) -> AuditEventPayload:
    return AuditEventPayload(
        event_id=str(uuid4()),
        timestamp=datetime.now(),
        user_id=user_id,
        role=role,
        action=action,
        object_type=object_type,
        object_id=object_id,
        request_id=request_id,
        status=status,
        detail=detail or {},
    )
