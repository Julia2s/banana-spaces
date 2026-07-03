"""Hybrid retrieval engine.

Три канала:
1. Lexical (BM25-подобный через TF-IDF на хэш-таблицах).
2. Vector (sentence-transformers LaBSE или Yandex embeddings).
3. Table (поиск по строкам таблиц с числовым фильтром).

Fusion: взвешенная сумма скорингов из каждого канала.
Кэш корпуса в памяти: загружается один раз, обновляется по требованию.
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable
from uuid import NAMESPACE_URL, uuid4, uuid5

from scientific_tangle_gateway.config import settings
from scientific_tangle_gateway.embeddings import EmbeddingsProvider
from scientific_tangle_gateway.schemas import (
    EvidenceBundlePayload,
    NormalizedDocumentPayload,
    QueryNumericConstraintPayload,
    RetrievalDocumentPayload,
    RetrievalHitPayload,
    RetrievalRunPayload,
    RetrievalTraceEntryPayload,
    RetrievalTracePayload,
    SourceSpanPayload,
)

logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
NUMBER_REGEX = re.compile(r"\d+(?:[\.,]\d+)?")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


class RetrievalCorpusLoader:
    """Загружает normalized artifacts из data/normalized. Кэш в памяти."""

    def __init__(
        self,
        normalized_dir: Path,
        source_corpus_dir: Path,
        source_char_limit: int = 8000,
    ) -> None:
        self.normalized_dir = normalized_dir
        self.source_corpus_dir = source_corpus_dir
        self.source_char_limit = source_char_limit
        self._cache: list[RetrievalDocumentPayload] | None = None
        self._cache_signature: str = ""

    def invalidate_cache(self) -> None:
        self._cache = None
        self._cache_signature = ""

    def load_documents(self) -> list[RetrievalDocumentPayload]:
        if self._cache is not None and self._cache_signature == self._signature():
            return self._cache

        docs = self._from_normalized_artifacts()
        if not docs:
            docs = self._from_source_corpus()

        self._cache = docs
        self._cache_signature = self._signature()
        return docs

    def _signature(self) -> str:
        if not self.normalized_dir.exists():
            return "empty"
        files = sorted(self.normalized_dir.rglob("*.json"))
        return f"{len(files)}:{files[-1].stat().st_mtime if files else 0}"

    def _from_normalized_artifacts(self) -> list[RetrievalDocumentPayload]:
        documents: list[RetrievalDocumentPayload] = []
        if not self.normalized_dir.exists():
            return documents

        for path in sorted(self.normalized_dir.glob("*/*.json")):
            try:
                normalized = NormalizedDocumentPayload.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except Exception as error:
                logger.warning("Ошибка чтения normalized artifact %s: %s", path, error)
                continue

            for span in normalized.source_spans:
                documents.append(
                    RetrievalDocumentPayload(
                        retrieval_document_id=f"{normalized.document_id}:{span.source_span_id}",
                        text=span.parsed_text or span.raw_text,
                        source_span_id=span.source_span_id,
                        document_id=normalized.document_id,
                        title=normalized.title,
                        source_type=normalized.source_type,
                        source_path=normalized.source_path,
                        access_level=span.access_level,
                        metadata={
                            "task_id": normalized.task_id,
                            "artifact_path": str(path),
                            "page": span.page,
                            "row_index": span.row_index,
                            "column_name": span.column_name,
                            "is_table_cell": span.table_id is not None,
                        },
                    )
                )
        return documents

    def _from_source_corpus(self) -> list[RetrievalDocumentPayload]:
        if not self.source_corpus_dir.exists():
            return []

        documents: list[RetrievalDocumentPayload] = []
        for path in sorted(self.source_corpus_dir.rglob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in {".txt", ".md", ".csv", ".pdf"}:
                continue

            text = self._read_source_text(path)
            if not text:
                continue

            text = text[: self.source_char_limit]
            document_id = str(uuid5(NAMESPACE_URL, str(path)))
            documents.append(
                RetrievalDocumentPayload(
                    retrieval_document_id=f"{document_id}:source",
                    text=text,
                    source_span_id=None,
                    document_id=document_id,
                    title=path.name,
                    source_type=suffix.lstrip("."),
                    source_path=str(path),
                    access_level="public",
                    metadata={"fallback_source": True},
                )
            )
        return documents

    def _read_source_text(self, path: Path) -> str:
        if path.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return ""
            try:
                reader = PdfReader(str(path))
            except Exception:
                return ""
            page_text = []
            for page in reader.pages[:5]:
                try:
                    page_text.append((page.extract_text() or "").strip())
                except Exception:
                    continue
            return "\n".join(chunk for chunk in page_text if chunk)

        for encoding in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return ""


class LexicalRetriever:
    """Лёгкий BM25-подобный retriever на лету. Для масштаба нужен Qdrant."""

    def retrieve(
        self,
        query: str,
        docs: list[RetrievalDocumentPayload],
        top_k: int,
    ) -> list[tuple[RetrievalDocumentPayload, float]]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        doc_tokens = [tokenize(doc.text) for doc in docs]
        doc_freq: dict[str, int] = defaultdict(int)
        for tokens in doc_tokens:
            for token in set(tokens):
                doc_freq[token] += 1

        doc_count = len(docs) or 1
        avgdl = sum(len(t) for t in doc_tokens) / doc_count or 1.0
        k1, b = 1.5, 0.75
        scores = []
        for doc, tokens in zip(docs, doc_tokens, strict=True):
            if not tokens:
                continue
            tf: dict[str, int] = defaultdict(int)
            for token in tokens:
                tf[token] += 1
            score = 0.0
            for token in query_tokens:
                if tf[token] == 0:
                    continue
                idf = math.log((doc_count - doc_freq[token] + 0.5) / (doc_freq[token] + 0.5) + 1.0)
                score += idf * (tf[token] * (k1 + 1)) / (tf[token] + k1 * (1 - b + b * len(tokens) / avgdl))
            if score > 0:
                scores.append((doc, score))

        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:top_k]


class VectorRetriever:
    """Векторный retriever на sentence-transformers или Yandex embeddings."""

    def __init__(self, embeddings: EmbeddingsProvider | None = None) -> None:
        self.embeddings = embeddings or EmbeddingsProvider()
        self._doc_cache: dict[str, list[float]] = {}

    def retrieve(
        self,
        query: str,
        docs: list[RetrievalDocumentPayload],
        top_k: int,
    ) -> list[tuple[RetrievalDocumentPayload, float]]:
        if not docs:
            return []
        query_vec = self.embeddings.embed_one(query)
        if not any(query_vec):
            return []

        texts_to_embed = []
        doc_for_text: list[RetrievalDocumentPayload] = []
        for doc in docs:
            text_key = doc.text[:1000]
            if text_key in self._doc_cache:
                continue
            texts_to_embed.append(text_key)
            doc_for_text.append(doc)

        if texts_to_embed:
            try:
                vectors = self.embeddings.embed(texts_to_embed)
                for doc, vec in zip(doc_for_text, vectors, strict=False):
                    self._doc_cache[doc.text[:1000]] = vec
            except Exception as error:
                logger.warning("Vector embedding failed: %s", error)
                return []

        scored = []
        for doc in docs:
            doc_vec = self._doc_cache.get(doc.text[:1000])
            if not doc_vec:
                continue
            score = self._cosine(query_vec, doc_vec)
            if score > 0:
                scored.append((doc, float(score)))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        return float(sum(a * b for a, b in zip(left, right, strict=True)))


class TableRetriever:
    """Поиск по строкам таблиц с учётом числовых ограничений.

    Извлекает из документных метаданных те, что помечены is_table_cell,
    группирует по source_span_id таблицы и оценивает релевантность строки.
    """

    def retrieve(
        self,
        query: str,
        docs: list[RetrievalDocumentPayload],
        top_k: int,
        numeric_constraints: list[QueryNumericConstraintPayload] | None = None,
    ) -> list[tuple[RetrievalDocumentPayload, float]]:
        query_tokens = set(tokenize(query))
        if not query_tokens:
            return []

        table_docs = [d for d in docs if d.metadata.get("is_table_cell")]
        if not table_docs:
            return []

        scored = []
        for doc in table_docs:
            doc_tokens = set(tokenize(doc.text))
            overlap = len(query_tokens & doc_tokens)
            if overlap == 0:
                continue
            score = overlap / (math.log(len(doc_tokens) + 2))
            if numeric_constraints:
                if not self._matches_constraints(doc.text, numeric_constraints):
                    score *= 0.1
            scored.append((doc, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    @staticmethod
    def _matches_constraints(text: str, constraints: list[QueryNumericConstraintPayload]) -> bool:
        for constraint in constraints:
            if constraint.min is None and constraint.max is None:
                continue
            found_match = False
            for match in NUMBER_REGEX.finditer(text):
                try:
                    value = float(match.group(0).replace(",", "."))
                except ValueError:
                    continue
                if constraint.min is not None and constraint.max is not None:
                    if constraint.min <= value <= constraint.max:
                        found_match = True
                        break
                elif constraint.max is not None and value <= constraint.max:
                    found_match = True
                    break
                elif constraint.min is not None and value >= constraint.min:
                    found_match = True
                    break
            if not found_match:
                return False
        return True


class NumericFilter:
    """Пост-фильтр для lexical/vector hits по числовым ограничениям из QueryIR."""

    @staticmethod
    def apply(
        hits: list[tuple[RetrievalDocumentPayload, float]],
        constraints: list[QueryNumericConstraintPayload] | None,
    ) -> list[tuple[RetrievalDocumentPayload, float]]:
        if not constraints:
            return hits
        filtered = []
        for doc, score in hits:
            if TableRetriever._matches_constraints(doc.text, constraints):
                filtered.append((doc, score))
        return filtered


class RetrievalRunStore:
    """In-memory store для retrieval runs. MVP-достаточно."""

    def __init__(self) -> None:
        self._runs: dict[str, RetrievalRunPayload] = {}

    def add(self, run: RetrievalRunPayload) -> RetrievalRunPayload:
        self._runs[run.run_id] = run
        return run

    def get(self, run_id: str) -> RetrievalRunPayload | None:
        return self._runs.get(run_id)


class HybridRetrievalService:
    """Оркестрирует lexical + vector + table retrievers с fusion."""

    def __init__(
        self,
        corpus_loader: RetrievalCorpusLoader,
        lexical_retriever: LexicalRetriever,
        vector_retriever: VectorRetriever,
        table_retriever: TableRetriever | None = None,
    ) -> None:
        self.corpus_loader = corpus_loader
        self.lexical_retriever = lexical_retriever
        self.vector_retriever = vector_retriever
        self.table_retriever = table_retriever or TableRetriever()

    def run(
        self,
        query_id: str,
        question: str,
        allowed_access_levels: Iterable[str],
        top_k: int,
        numeric_constraints: list[QueryNumericConstraintPayload] | None = None,
    ) -> EvidenceBundlePayload:
        docs = self.corpus_loader.load_documents()
        allowed = set(allowed_access_levels)
        filtered_docs = [doc for doc in docs if doc.access_level in allowed]

        lexical_hits = self.lexical_retriever.retrieve(question, filtered_docs, top_k=top_k * 3)
        vector_hits = self.vector_retriever.retrieve(question, filtered_docs, top_k=top_k * 3)
        table_hits = self.table_retriever.retrieve(
            question,
            filtered_docs,
            top_k=top_k * 2,
            numeric_constraints=numeric_constraints,
        )

        lexical_hits = NumericFilter.apply(lexical_hits, numeric_constraints)
        vector_hits = NumericFilter.apply(vector_hits, numeric_constraints)

        fusion_hits = self._fuse_hits(lexical_hits, vector_hits, table_hits, top_k=top_k)

        retrieval_trace = RetrievalTracePayload(
            lexical=self._trace_entries(lexical_hits),
            vector=self._trace_entries(vector_hits),
            fusion=self._trace_entries(fusion_hits),
        )

        source_spans = [
            SourceSpanPayload(
                source_span_id=hit[0].source_span_id or f"{hit[0].document_id}:source",
                document_id=hit[0].document_id,
                raw_text=hit[0].text,
                parsed_text=hit[0].text,
                access_level=hit[0].access_level,
            )
            for hit in fusion_hits
        ]

        top_hits = [
            RetrievalHitPayload(
                retrieval_document_id=doc.retrieval_document_id,
                source_span_id=doc.source_span_id,
                document_id=doc.document_id,
                title=doc.title,
                source_type=doc.source_type,
                source_path=doc.source_path,
                access_level=doc.access_level,
                text=doc.text,
                score=score,
                channels=self._channels_for_doc(doc, lexical_hits, vector_hits, table_hits),
            )
            for doc, score in fusion_hits
        ]

        warnings = []
        if not filtered_docs:
            warnings.append("Нет доступных документов для текущей роли")
        if filtered_docs and not top_hits:
            warnings.append("Ретриверы не нашли релевантных фрагментов")
        if numeric_constraints and filtered_docs:
            total_hits = len(lexical_hits) + len(vector_hits)
            if total_hits == 0:
                warnings.append("Числовые ограничения отфильтровали все результаты")

        return EvidenceBundlePayload(
            query_id=query_id,
            retrieval_trace=retrieval_trace,
            source_spans=source_spans,
            warnings=warnings,
            top_hits=top_hits,
        )

    def _fuse_hits(
        self,
        lexical_hits: list[tuple[RetrievalDocumentPayload, float]],
        vector_hits: list[tuple[RetrievalDocumentPayload, float]],
        table_hits: list[tuple[RetrievalDocumentPayload, float]],
        top_k: int,
    ) -> list[tuple[RetrievalDocumentPayload, float]]:
        def normalize(hits: list[tuple[RetrievalDocumentPayload, float]]) -> dict[str, float]:
            if not hits:
                return {}
            max_score = max(s for _, s in hits) or 1.0
            return {doc.retrieval_document_id: score / max_score for doc, score in hits}

        lex_norm = normalize(lexical_hits)
        vec_norm = normalize(vector_hits)
        tab_norm = normalize(table_hits)

        all_ids = set(lex_norm) | set(vec_norm) | set(tab_norm)
        doc_map: dict[str, RetrievalDocumentPayload] = {}
        for doc, _ in lexical_hits + vector_hits + table_hits:
            doc_map[doc.retrieval_document_id] = doc

        fused = []
        for doc_id in all_ids:
            score = (
                0.40 * lex_norm.get(doc_id, 0.0)
                + 0.35 * vec_norm.get(doc_id, 0.0)
                + 0.25 * tab_norm.get(doc_id, 0.0)
            )
            fused.append((doc_map[doc_id], score))

        fused.sort(key=lambda item: item[1], reverse=True)
        return fused[:top_k]

    def _trace_entries(
        self,
        hits: list[tuple[RetrievalDocumentPayload, float]],
    ) -> list[RetrievalTraceEntryPayload]:
        return [
            RetrievalTraceEntryPayload(
                retrieval_document_id=doc.retrieval_document_id,
                score=score,
            )
            for doc, score in hits
        ]

    def _channels_for_doc(
        self,
        doc: RetrievalDocumentPayload,
        lexical_hits: list[tuple[RetrievalDocumentPayload, float]],
        vector_hits: list[tuple[RetrievalDocumentPayload, float]],
        table_hits: list[tuple[RetrievalDocumentPayload, float]],
    ) -> list[str]:
        channels = []
        if any(item[0].retrieval_document_id == doc.retrieval_document_id for item in lexical_hits):
            channels.append("lexical")
        if any(item[0].retrieval_document_id == doc.retrieval_document_id for item in vector_hits):
            channels.append("vector")
        if any(item[0].retrieval_document_id == doc.retrieval_document_id for item in table_hits):
            channels.append("table")
        return channels


def generate_run_id() -> str:
    return str(uuid4())
