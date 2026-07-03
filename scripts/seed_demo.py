"""Загрузка demo corpus через API.

Использование:
    python scripts/seed_demo.py --corpus demo/seed_data/
    python scripts/seed_demo.py --corpus demo/seed_data/ --api http://localhost:8000 --access internal
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def seed(
    corpus_dir: Path,
    api_url: str,
    access_level: str,
    wait_seconds: float = 60.0,
    poll_interval: float = 1.0,
) -> int:
    files = sorted(
        p for p in corpus_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in {".pdf", ".txt", ".md", ".csv", ".xlsx", ".docx"}
    )
    if not files:
        logger.error("В каталоге %s нет поддерживаемых файлов", corpus_dir)
        return 1

    logger.info("Найдено файлов для загрузки: %d", len(files))
    failed: list[str] = []

    for file_path in files:
        logger.info("Загрузка: %s", file_path.name)
        try:
            with file_path.open("rb") as fp:
                response = httpx.post(
                    f"{api_url}/api/documents/upload",
                    data={"access_level": access_level},
                    files={"files": (file_path.name, fp, "application/octet-stream")},
                    timeout=60.0,
                )
            response.raise_for_status()
            task_id = response.json()["task_id"]

            start_response = httpx.post(
                f"{api_url}/api/tasks/{task_id}/start",
                timeout=10.0,
            )
            start_response.raise_for_status()

            if not _wait_for_completed(api_url, task_id, wait_seconds, poll_interval):
                logger.error("Task %s не завершилась за %.0fs", task_id, wait_seconds)
                failed.append(file_path.name)
                continue

            task_response = httpx.get(f"{api_url}/api/tasks/{task_id}", timeout=10.0)
            task_data = task_response.json()
            logger.info(
                "  ✓ %s — статус %s, spans=%d, warnings=%d",
                file_path.name,
                task_data["status"],
                _get_span_count(api_url, task_id),
                len(task_data.get("warnings", [])),
            )
        except Exception as error:
            logger.error("  ✗ %s — %s", file_path.name, error)
            failed.append(file_path.name)

    logger.info("Готово. Успешно: %d, провалено: %d", len(files) - len(failed), len(failed))
    if failed:
        logger.warning("Провалены: %s", ", ".join(failed))
        return 2

    health = httpx.get(f"{api_url}/api/health/detail", timeout=10.0).json()
    logger.info("Graph stats: %s", health.get("neo4j_stats", {}))
    return 0


def _wait_for_completed(api_url: str, task_id: str, timeout: float, interval: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{api_url}/api/tasks/{task_id}", timeout=10.0)
            data = response.json()
            status = data["status"]
            if status == "completed":
                return True
            if status == "failed":
                logger.error("Task failed: %s", data.get("error_message"))
                return False
        except Exception as error:
            logger.warning("Poll error: %s", error)
        time.sleep(interval)
    return False


def _get_span_count(api_url: str, task_id: str) -> int:
    try:
        response = httpx.get(f"{api_url}/api/tasks/{task_id}/documents", timeout=10.0)
        docs = response.json()
        return sum(d.get("source_span_count", 0) for d in docs)
    except Exception:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo corpus into ScientificTangle gateway")
    parser.add_argument("--corpus", type=Path, default=Path("demo/seed_data"), help="Каталог с файлами")
    parser.add_argument("--api", type=str, default="http://localhost:8000", help="URL gateway")
    parser.add_argument("--access", type=str, default="internal", help="Уровень доступа")
    parser.add_argument("--wait", type=float, default=120.0, help="Таймаут ожидания обработки файла")
    args = parser.parse_args()

    return seed(args.corpus, args.api, args.access, args.wait)


if __name__ == "__main__":
    sys.exit(main())
