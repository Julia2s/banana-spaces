from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from scientific_tangle_gateway.schemas import (
    AccessLevel,
    IngestionFilePayload,
    IngestionTaskPayload,
    IngestionTaskStatus,
    utc_now,
)

ALLOWED_STATUS_TRANSITIONS: dict[IngestionTaskStatus, set[IngestionTaskStatus]] = {
    "uploaded": {"queued", "failed"},
    "queued": {"parsing", "failed"},
    "parsing": {"normalized", "failed"},
    "normalized": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
}


class IngestionTaskTransitionError(ValueError):
    pass


class IngestionTaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, IngestionTaskPayload] = {}

    def add(self, task: IngestionTaskPayload) -> IngestionTaskPayload:
        self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> IngestionTaskPayload | None:
        return self._tasks.get(task_id)

    def update_status(
        self,
        task_id: str,
        status: IngestionTaskStatus,
        warning: str | None = None,
        error_message: str | None = None,
    ) -> IngestionTaskPayload | None:
        task = self.get(task_id)
        if task is None:
            return None

        allowed = ALLOWED_STATUS_TRANSITIONS[task.status]
        if status not in allowed:
            raise IngestionTaskTransitionError(f"{task.status} -> {status}")

        now = utc_now()
        warnings = [*task.warnings]
        if warning is not None:
            warnings.append(warning)

        updated = task.model_copy(
            update={
                "status": status,
                "updated_at": now,
                "started_at": (
                    now
                    if status in {"queued", "parsing"} and task.started_at is None
                    else task.started_at
                ),
                "completed_at": now if status in {"completed", "failed"} else task.completed_at,
                "error_message": error_message,
                "warnings": warnings,
            }
        )
        self._tasks[task_id] = updated
        return updated


class LocalUploadStorage:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    async def save_files(
        self,
        files: list[UploadFile],
        access_level: AccessLevel,
    ) -> IngestionTaskPayload:
        task_id = str(uuid4())
        task_dir = self.root_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=False)

        saved_files = []
        warnings = []

        for file in files:
            safe_name = self._safe_filename(file.filename)
            destination = self._next_available_path(task_dir / safe_name)
            size_bytes = await self._write_upload(file, destination)
            saved_files.append(
                IngestionFilePayload(
                    filename=safe_name,
                    content_type=file.content_type,
                    size_bytes=size_bytes,
                    storage_path=str(destination),
                )
            )
            if size_bytes == 0:
                warnings.append(f"Файл {safe_name} пустой")

        now = utc_now()
        return IngestionTaskPayload(
            task_id=task_id,
            status="uploaded",
            access_level=access_level,
            files=saved_files,
            created_at=now,
            updated_at=now,
            warnings=warnings,
        )

    def _safe_filename(self, filename: str | None) -> str:
        normalized = (
            (filename or "uploaded_file")
            .replace("\\", "/")
            .split("/")[-1]
            .strip()
        )
        if normalized in {"", ".", ".."}:
            return "uploaded_file"
        return normalized

    def _next_available_path(self, path: Path) -> Path:
        if not path.exists():
            return path

        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        index = 2

        while True:
            candidate = parent / f"{stem}_{index}{suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    async def _write_upload(self, file: UploadFile, destination: Path) -> int:
        size_bytes = 0
        with destination.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                size_bytes += len(chunk)
        await file.close()
        return size_bytes
