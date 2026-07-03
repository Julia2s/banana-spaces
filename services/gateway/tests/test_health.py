import psycopg
import pytest
from fastapi.testclient import TestClient

from scientific_tangle_gateway.config import settings
from scientific_tangle_gateway.main import create_app


def test_health_returns_ok() -> None:
    if not _postgres_available(settings.db_dsn):
        pytest.skip("PostgreSQL недоступен для integration tests")
    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_meta_marks_contracts_as_draft() -> None:
    if not _postgres_available(settings.db_dsn):
        pytest.skip("PostgreSQL недоступен для integration tests")
    with TestClient(create_app()) as client:
        response = client.get("/api/meta")
        assert response.status_code == 200
        assert response.json()["contracts_status"] == "draft"


def _postgres_available(dsn: str) -> bool:
    try:
        with psycopg.connect(dsn):
            return True
    except Exception:
        return False
