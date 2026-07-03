"""End-to-end smoke: один официальный вопрос через /api/query.

Использование:
    python scripts/e2e_smoke.py
    python scripts/e2e_smoke.py --api http://localhost:8000 --question "..."
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


DEFAULT_QUESTIONS = [
    "Какие методы обессоливания воды подходят для обогатительной фабрики при содержании сульфатов 200 мг/л и требуемом сухом остатке не более 1000 мг/дм³?",
    "Какие технические решения организации циркуляции католита при электроэкстракции никеля описаны в мировой практике?",
]


def run_e2e(api_url: str, question: str, role: str = "researcher") -> bool:
    logger.info("Вопрос: %s", question)
    try:
        response = httpx.post(
            f"{api_url}/api/query",
            json={"question": question, "role": role, "top_k": 10},
            timeout=120.0,
        )
        response.raise_for_status()
    except Exception as error:
        logger.error("API вызов провалился: %s", error)
        return False

    answer = response.json()
    logger.info("Answer ID: %s", answer["answer_id"])
    logger.info("Confidence: %s", answer["confidence"])
    logger.info("Generator: %s", answer["generator"])
    logger.info("Источников: %d", len(answer.get("source_links", [])))
    logger.info("Gaps: %d", len(answer.get("gaps", [])))
    logger.info("Conflicts: %d", len(answer.get("conflicts", [])))

    if answer.get("warnings"):
        logger.warning("Warnings: %s", "; ".join(answer["warnings"]))

    text = answer.get("answer_text", "")
    if text:
        logger.info("---- ОТВЕТ ----")
        print(text)
        print()
    else:
        logger.error("Пустой ответ")
        return False

    if not answer.get("source_links"):
        logger.error("Ответ без источников — e2e провален")
        return False

    logger.info("---- Источники ----")
    for link in answer["source_links"]:
        logger.info(
            "  [%d] %s (%s) score=%.3f channels=%s",
            link["n"],
            link["title"],
            link["source_type"],
            link["score"],
            ",".join(link.get("channels", [])),
        )

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="E2E smoke для ScientificTangle")
    parser.add_argument("--api", type=str, default="http://localhost:8000")
    parser.add_argument("--question", type=str, default=None)
    parser.add_argument("--role", type=str, default="researcher")
    args = parser.parse_args()

    questions = [args.question] if args.question else DEFAULT_QUESTIONS

    all_ok = True
    for q in questions:
        ok = run_e2e(args.api, q, args.role)
        if not ok:
            all_ok = False

    if all_ok:
        logger.info("✓ E2E SMOKE PASSED")
        return 0
    logger.error("✗ E2E SMOKE FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
