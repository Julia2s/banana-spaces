import json
from datetime import datetime

import psycopg

from scientific_tangle_gateway.ingestion import (
    ALLOWED_STATUS_TRANSITIONS,
    IngestionTaskTransitionError,
)
from scientific_tangle_gateway.schemas import (
    IngestionFilePayload,
    IngestionTaskPayload,
    IngestionTaskStatus,
)


class TaskRepository:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def init_db(self) -> None:
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_tasks (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    access_level TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    started_at TIMESTAMPTZ NULL,
                    completed_at TIMESTAMPTZ NULL,
                    error_message TEXT NULL,
                    warnings_json TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_files (
                    id BIGSERIAL PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES ingestion_tasks(task_id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    content_type TEXT NULL,
                    size_bytes BIGINT NOT NULL,
                    storage_path TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def create_task(self, task: IngestionTaskPayload) -> IngestionTaskPayload:
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ingestion_tasks (
                    task_id, status, access_level, created_at, updated_at,
                    started_at, completed_at, error_message, warnings_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    task.task_id,
                    task.status,
                    task.access_level,
                    task.created_at,
                    task.updated_at,
                    task.started_at,
                    task.completed_at,
                    task.error_message,
                    json.dumps(task.warnings, ensure_ascii=False),
                ),
            )

            for file_payload in task.files:
                cursor.execute(
                    """
                    INSERT INTO ingestion_files (
                        task_id, filename, content_type, size_bytes, storage_path
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        task.task_id,
                        file_payload.filename,
                        file_payload.content_type,
                        file_payload.size_bytes,
                        file_payload.storage_path,
                    ),
                )
            conn.commit()
        return task

    def get_task(self, task_id: str) -> IngestionTaskPayload | None:
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT task_id, status, access_level, created_at, updated_at,
                       started_at, completed_at, error_message, warnings_json
                FROM ingestion_tasks
                WHERE task_id = %s
                """,
                (task_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            files = self._get_files(cursor, task_id)
            return self._to_task_payload(row, files)

    def list_tasks_by_status(
        self,
        status: IngestionTaskStatus,
        limit: int = 10,
    ) -> list[IngestionTaskPayload]:
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT task_id, status, access_level, created_at, updated_at,
                       started_at, completed_at, error_message, warnings_json
                FROM ingestion_tasks
                WHERE status = %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (status, limit),
            )
            rows = cursor.fetchall()
            tasks = []
            for row in rows:
                task_id = row[0]
                files = self._get_files(cursor, task_id)
                tasks.append(self._to_task_payload(row, files))
            return tasks

    def update_status(
        self,
        task_id: str,
        status: IngestionTaskStatus,
        warning: str | None = None,
        error_message: str | None = None,
    ) -> IngestionTaskPayload | None:
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT task_id, status, access_level, created_at, updated_at,
                       started_at, completed_at, error_message, warnings_json
                FROM ingestion_tasks
                WHERE task_id = %s
                FOR UPDATE
                """,
                (task_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            current_status: IngestionTaskStatus = row[1]
            allowed = ALLOWED_STATUS_TRANSITIONS[current_status]
            if status not in allowed:
                raise IngestionTaskTransitionError(f"{current_status} -> {status}")

            now = datetime.now().astimezone()
            started_at = row[5]
            completed_at = row[6]
            warnings = json.loads(row[8]) if row[8] else []

            if warning is not None:
                warnings.append(warning)

            if status in {"queued", "parsing"} and started_at is None:
                started_at = now
            if status in {"completed", "failed"}:
                completed_at = now

            cursor.execute(
                """
                UPDATE ingestion_tasks
                SET status = %s,
                    updated_at = %s,
                    started_at = %s,
                    completed_at = %s,
                    error_message = %s,
                    warnings_json = %s
                WHERE task_id = %s
                """,
                (
                    status,
                    now,
                    started_at,
                    completed_at,
                    error_message,
                    json.dumps(warnings, ensure_ascii=False),
                    task_id,
                ),
            )
            conn.commit()

            cursor.execute(
                """
                SELECT task_id, status, access_level, created_at, updated_at,
                       started_at, completed_at, error_message, warnings_json
                FROM ingestion_tasks
                WHERE task_id = %s
                """,
                (task_id,),
            )
            updated_row = cursor.fetchone()
            if updated_row is None:
                return None
            files = self._get_files(cursor, task_id)
            return self._to_task_payload(updated_row, files)

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn)

    def _get_files(
        self,
        cursor: psycopg.Cursor,
        task_id: str,
    ) -> list[IngestionFilePayload]:
        cursor.execute(
            """
            SELECT filename, content_type, size_bytes, storage_path
            FROM ingestion_files
            WHERE task_id = %s
            ORDER BY id ASC
            """,
            (task_id,),
        )
        rows = cursor.fetchall()
        return [
            IngestionFilePayload(
                filename=row[0],
                content_type=row[1],
                size_bytes=row[2],
                storage_path=row[3],
            )
            for row in rows
        ]

    def _to_task_payload(
        self,
        row: tuple,
        files: list[IngestionFilePayload],
    ) -> IngestionTaskPayload:
        return IngestionTaskPayload(
            task_id=row[0],
            status=row[1],
            access_level=row[2],
            files=files,
            created_at=row[3],
            updated_at=row[4],
            started_at=row[5],
            completed_at=row[6],
            error_message=row[7],
            warnings=json.loads(row[8]) if row[8] else [],
        )
