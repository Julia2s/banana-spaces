"""Background ingestion worker.

Polling queued tasks, normalizes documents, runs extraction,
writes to Neo4j knowledge graph.

Lifecycle: uploaded → queued → parsing → normalized → extracted → completed | failed
"""

from __future__ import annotations

import asyncio
import logging

from scientific_tangle_gateway.claims import build_claims
from scientific_tangle_gateway.extractor import KnowledgeExtractor
from scientific_tangle_gateway.graph import KnowledgeGraph
from scientific_tangle_gateway.ingestion import IngestionTaskTransitionError
from scientific_tangle_gateway.normalization import (
    DocumentNormalizer,
    LocalNormalizedDocumentStore,
)
from scientific_tangle_gateway.task_repository import TaskRepository

logger = logging.getLogger(__name__)


class IngestionTaskWorker:
    def __init__(
        self,
        repository: TaskRepository,
        normalizer: DocumentNormalizer,
        document_store: LocalNormalizedDocumentStore,
        extractor: KnowledgeExtractor | None = None,
        graph: KnowledgeGraph | None = None,
        poll_interval_seconds: float = 1.0,
        batch_size: int = 10,
    ) -> None:
        self.repository = repository
        self.normalizer = normalizer
        self.document_store = document_store
        self.extractor = extractor or KnowledgeExtractor()
        self.graph = graph or KnowledgeGraph()
        self.poll_interval_seconds = poll_interval_seconds
        self.batch_size = batch_size
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            try:
                self.graph.init_schema()
            except Exception as error:
                logger.warning("Neo4j schema init failed: %s", error)
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None
        self.graph.close()

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            await self._process_once()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.poll_interval_seconds,
                )
            except TimeoutError:
                continue

    async def _process_once(self) -> None:
        queued_tasks = self.repository.list_tasks_by_status("queued", limit=self.batch_size)
        for task in queued_tasks:
            try:
                parsing_task = self.repository.update_status(task.task_id, status="parsing")
            except IngestionTaskTransitionError:
                continue

            if parsing_task is None:
                continue

            try:
                documents = [
                    self.normalizer.normalize_file(
                        task_id=parsing_task.task_id,
                        file_payload=file_payload,
                        access_level=parsing_task.access_level,
                    )
                    for file_payload in parsing_task.files
                ]
                self.document_store.save_task_documents(
                    task_id=parsing_task.task_id,
                    documents=documents,
                )
                self.repository.update_status(parsing_task.task_id, status="normalized")

                await asyncio.to_thread(
                    self._extract_and_index,
                    documents=documents,
                )

                self.repository.update_status(parsing_task.task_id, status="completed")
            except Exception as error:
                logger.exception("Ingestion failed for task %s", parsing_task.task_id)
                try:
                    self.repository.update_status(
                        parsing_task.task_id,
                        status="failed",
                        error_message=str(error),
                    )
                except IngestionTaskTransitionError:
                    continue

    def _extract_and_index(self, documents) -> None:
        """Запускается в отдельном потоке: extraction + запись в граф."""
        if not self.graph.available:
            logger.info("Neo4j недоступен, extraction пропущен")
            return

        for doc in documents:
            try:
                doc_dict = doc.model_dump(mode="json")
                self.graph.write_document({
                    "document_id": doc.document_id,
                    "title": doc.title,
                    "source_type": doc.source_type,
                    "access_level": doc.access_level,
                })

                for span in doc.source_spans:
                    span_dict = span.model_dump(mode="json")
                    self.graph.write_source_span(span_dict)

                    text = span.parsed_text or span.raw_text
                    extraction = self.extractor.extract(text, span.source_span_id)

                    for entity in extraction.entities:
                        self.graph.write_entity(
                            entity_id=entity.canonical_id,
                            name=entity.name,
                            entity_type=entity.entity_type,
                            source_span_id=span.source_span_id,
                            chemical_formula=entity.chemical_formula,
                        )

                    built_claims = build_claims(extraction)
                    for claim in built_claims:
                        self.graph.write_claim(
                            claim_id=claim.claim_id,
                            text=claim.text,
                            source_span_id=claim.source_span_id,
                            status=claim.status,
                            confidence=claim.confidence,
                            extractor=claim.extractor,
                            entity_names=claim.entities,
                        )
            except Exception as error:
                logger.warning("Extraction failed for document %s: %s", doc.document_id, error)
