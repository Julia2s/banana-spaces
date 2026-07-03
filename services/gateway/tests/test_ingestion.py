import time
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from scientific_tangle_gateway.config import settings
from scientific_tangle_gateway.main import create_app
from scientific_tangle_gateway.task_repository import TaskRepository


def make_test_client(tmp_path: Path) -> TestClient:
    if not _postgres_available(settings.db_dsn):
        pytest.skip("PostgreSQL недоступен для integration tests")

    settings.raw_upload_dir = tmp_path / "raw"
    settings.normalized_dir = tmp_path / "normalized"
    settings.worker_poll_interval_seconds = 0.05
    settings.worker_batch_size = 20
    _truncate_ingestion_tables(settings.db_dsn)
    return TestClient(create_app())


def _postgres_available(dsn: str) -> bool:
    try:
        repository = TaskRepository(dsn)
        repository.init_db()
        return True
    except Exception:
        return False


def _truncate_ingestion_tables(dsn: str) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        cursor.execute("DELETE FROM ingestion_files")
        cursor.execute("DELETE FROM ingestion_tasks")
        conn.commit()


def _wait_for_status(
    client: TestClient,
    task_id: str,
    expected_status: str,
    timeout_seconds: float = 5.0,
) -> dict:
    started_at = time.time()
    while time.time() - started_at < timeout_seconds:
        payload = client.get(f"/api/tasks/{task_id}").json()
        if payload["status"] == expected_status:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Task {task_id} не достиг статуса {expected_status}")


def test_upload_creates_ingestion_task_in_postgres(tmp_path: Path) -> None:
    with make_test_client(tmp_path) as client:
        response = client.post(
            "/api/documents/upload",
            data={"access_level": "public"},
            files=[("files", ("demo.txt", b"source text", "text/plain"))],
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "uploaded"
        assert payload["access_level"] == "public"
        assert payload["files"][0]["filename"] == "demo.txt"
        assert Path(payload["files"][0]["storage_path"]).read_bytes() == b"source text"

        task_response = client.get(f"/api/tasks/{payload['task_id']}")
        assert task_response.status_code == 200
        assert task_response.json()["task_id"] == payload["task_id"]


def test_unknown_ingestion_task_returns_404(tmp_path: Path) -> None:
    with make_test_client(tmp_path) as client:
        response = client.get("/api/tasks/missing")
        assert response.status_code == 404


def test_upload_strips_path_from_filename(tmp_path: Path) -> None:
    with make_test_client(tmp_path) as client:
        response = client.post(
            "/api/documents/upload",
            files=[("files", ("../nested\\demo.txt", b"source text", "text/plain"))],
        )
        assert response.status_code == 202
        assert response.json()["files"][0]["filename"] == "demo.txt"


def test_start_ingestion_task_creates_normalized_document(tmp_path: Path) -> None:
    with make_test_client(tmp_path) as client:
        upload_response = client.post(
            "/api/documents/upload",
            files=[("files", ("demo.txt", b"source text", "text/plain"))],
        )
        task_id = upload_response.json()["task_id"]

        response = client.post(f"/api/tasks/{task_id}/start")
        assert response.status_code == 200
        assert response.json()["status"] == "queued"

        completed_payload = _wait_for_status(client, task_id, "completed")
        assert completed_payload["started_at"] is not None
        assert completed_payload["completed_at"] is not None

        documents_response = client.get(f"/api/tasks/{task_id}/documents")
        assert documents_response.status_code == 200
        documents = documents_response.json()
        assert documents[0]["source_span_count"] == 1

        document_id = documents[0]["document_id"]
        document_response = client.get(f"/api/documents/{document_id}")
        assert document_response.status_code == 200
        document = document_response.json()
        assert document["title"] == "demo.txt"
        assert document["source_spans"][0]["raw_text"] == "source text"


def test_restarting_ingestion_task_returns_conflict(tmp_path: Path) -> None:
    with make_test_client(tmp_path) as client:
        upload_response = client.post(
            "/api/documents/upload",
            files=[("files", ("demo.txt", b"source text", "text/plain"))],
        )
        task_id = upload_response.json()["task_id"]

        first_response = client.post(f"/api/tasks/{task_id}/start")
        second_response = client.post(f"/api/tasks/{task_id}/start")
        assert first_response.status_code == 200
        assert second_response.status_code == 409


def test_start_unknown_ingestion_task_returns_404(tmp_path: Path) -> None:
    with make_test_client(tmp_path) as client:
        response = client.post("/api/tasks/missing/start")
        assert response.status_code == 404


def test_empty_file_creates_warning_without_source_span(tmp_path: Path) -> None:
    with make_test_client(tmp_path) as client:
        upload_response = client.post(
            "/api/documents/upload",
            files=[("files", ("empty.txt", b"", "text/plain"))],
        )
        task_id = upload_response.json()["task_id"]

        start_response = client.post(f"/api/tasks/{task_id}/start")
        _wait_for_status(client, task_id, "completed")
        documents_response = client.get(f"/api/tasks/{task_id}/documents")
        document_id = documents_response.json()[0]["document_id"]
        document_response = client.get(f"/api/documents/{document_id}")

        assert start_response.status_code == 200
        assert start_response.json()["status"] == "queued"
        assert documents_response.json()[0]["source_span_count"] == 0
        assert document_response.json()["source_spans"] == []
        assert document_response.json()["parse_warnings"]


def test_pdf_without_extractable_text_creates_parse_warning(tmp_path: Path) -> None:
    with make_test_client(tmp_path) as client:
        upload_response = client.post(
            "/api/documents/upload",
            files=[
                ("files", ("broken.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")),
            ],
        )
        task_id = upload_response.json()["task_id"]

        start_response = client.post(f"/api/tasks/{task_id}/start")
        _wait_for_status(client, task_id, "completed")
        documents_response = client.get(f"/api/tasks/{task_id}/documents")
        document_id = documents_response.json()[0]["document_id"]
        document_response = client.get(f"/api/documents/{document_id}")

        assert start_response.status_code == 200
        assert start_response.json()["status"] == "queued"
        assert document_response.json()["source_type"] == "pdf"
        assert document_response.json()["source_spans"] == []
        assert document_response.json()["parse_warnings"]


def test_worker_sets_failed_status_on_normalization_error(tmp_path: Path) -> None:
    with make_test_client(tmp_path) as client:
        upload_response = client.post(
            "/api/documents/upload",
            files=[("files", ("broken.txt", b"source text", "text/plain"))],
        )
        task_id = upload_response.json()["task_id"]

        with psycopg.connect(settings.db_dsn) as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ingestion_files
                SET storage_path = %s
                WHERE task_id = %s
                """,
                ("Z:/non-existent-path/broken.txt", task_id),
            )
            conn.commit()

        start_response = client.post(f"/api/tasks/{task_id}/start")
        failed_payload = _wait_for_status(client, task_id, "failed")

        assert start_response.status_code == 200
        assert start_response.json()["status"] == "queued"
        assert failed_payload["error_message"]
