"""Neo4j knowledge graph adapter.

Запись и чтение сущностей, claims, source spans, evidence.
Схема графа (упрощённая, операционная):

Узлы:
  (:Document {document_id, title, source_type, access_level, ingested_at})
  (:SourceSpan {source_span_id, document_id, page, row_index, column_name, raw_text})
  (:Entity {entity_id, name, entity_type, chemical_formula})
  (:Claim {claim_id, text, status, confidence, extractor, extracted_at})

Связи:
  (:Document)-[:HAS_SPAN]->(:SourceSpan)
  (:SourceSpan)-[:MENTIONS]->(:Entity)
  (:Claim)-[:EVIDENCED_BY]->(:SourceSpan)
  (:Claim)-[:ABOUT]->(:Entity)
  (:Entity)-[:HAS_ALIAS {alias}]->(:Entity)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from scientific_tangle_gateway.config import settings

logger = logging.getLogger(__name__)

try:
    from neo4j import GraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:
    GraphDatabase = None
    NEO4J_AVAILABLE = False


SCHEMA_QUERIES = [
    "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.document_id IS UNIQUE",
    "CREATE CONSTRAINT source_span_id IF NOT EXISTS FOR (s:SourceSpan) REQUIRE s.source_span_id IS UNIQUE",
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE",
    "CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.claim_id IS UNIQUE",
    "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)",
    "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)",
    "CREATE INDEX claim_status IF NOT EXISTS FOR (c:Claim) ON (c.status)",
]


class GraphNotAvailable(RuntimeError):
    pass


class KnowledgeGraph:
    """Neo4j adapter с деградацией: если БД недоступна, методы становятся no-op."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        self.uri = uri or settings.neo4j_uri
        self.user = user or settings.neo4j_user
        self.password = password or settings.neo4j_password
        self._driver = None
        self._available: bool | None = None

    @property
    def available(self) -> bool:
        if self._available is not None:
            return self._available
        if not NEO4J_AVAILABLE:
            self._available = False
            return False
        try:
            self._ensure_driver()
            with self._driver.session() as session:
                session.run("RETURN 1").consume()
            self._available = True
        except Exception as error:
            logger.warning("Neo4j недоступен: %s", error)
            self._available = False
        return self._available

    def _ensure_driver(self):
        if self._driver is None:
            if not NEO4J_AVAILABLE:
                raise GraphNotAvailable("neo4j package не установлен")
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def init_schema(self) -> None:
        if not self.available:
            return
        with self._driver.session() as session:
            for query in SCHEMA_QUERIES:
                session.run(query).consume()

    def write_document(self, document: dict[str, Any]) -> None:
        if not self.available:
            return
        query = """
        MERGE (d:Document {document_id: $document_id})
        SET d.title = $title,
            d.source_type = $source_type,
            d.access_level = $access_level,
            d.ingested_at = $ingested_at
        """
        with self._driver.session() as session:
            session.run(
                query,
                document_id=document["document_id"],
                title=document.get("title", ""),
                source_type=document.get("source_type", ""),
                access_level=document.get("access_level", "internal"),
                ingested_at=datetime.now(UTC).isoformat(),
            ).consume()

    def write_source_span(self, span: dict[str, Any]) -> None:
        if not self.available:
            return
        query = """
        MATCH (d:Document {document_id: $document_id})
        MERGE (s:SourceSpan {source_span_id: $source_span_id})
        SET s.document_id = $document_id,
            s.page = $page,
            s.row_index = $row_index,
            s.column_name = $column_name,
            s.raw_text = $raw_text,
            s.parsed_text = $parsed_text,
            s.access_level = $access_level
        MERGE (d)-[:HAS_SPAN]->(s)
        """
        with self._driver.session() as session:
            session.run(
                query,
                document_id=span["document_id"],
                source_span_id=span["source_span_id"],
                page=span.get("page"),
                row_index=span.get("row_index"),
                column_name=span.get("column_name"),
                raw_text=span.get("raw_text", "")[:2000],
                parsed_text=(span.get("parsed_text") or "")[:2000],
                access_level=span.get("access_level", "internal"),
            ).consume()

    def write_entity(
        self,
        entity_id: str,
        name: str,
        entity_type: str,
        source_span_id: str,
        chemical_formula: str | None = None,
    ) -> None:
        if not self.available:
            return
        query = """
        MATCH (s:SourceSpan {source_span_id: $source_span_id})
        MERGE (e:Entity {entity_id: $entity_id})
        SET e.name = $name,
            e.entity_type = $entity_type,
            e.chemical_formula = coalesce($chemical_formula, e.chemical_formula)
        MERGE (s)-[:MENTIONS]->(e)
        """
        with self._driver.session() as session:
            session.run(
                query,
                entity_id=entity_id,
                name=name,
                entity_type=entity_type,
                chemical_formula=chemical_formula,
                source_span_id=source_span_id,
            ).consume()

    def write_claim(
        self,
        claim_id: str,
        text: str,
        source_span_id: str,
        status: str,
        confidence: float,
        extractor: str,
        entity_names: list[str],
    ) -> None:
        if not self.available:
            return
        query = """
        MATCH (s:SourceSpan {source_span_id: $source_span_id})
        MERGE (c:Claim {claim_id: $claim_id})
        SET c.text = $text,
            c.status = $status,
            c.confidence = $confidence,
            c.extractor = $extractor,
            c.extracted_at = $extracted_at
        MERGE (c)-[:EVIDENCED_BY]->(s)
        WITH c, $entity_names AS names
        UNWIND names AS name
        MATCH (e:Entity {name: name})
        MERGE (c)-[:ABOUT]->(e)
        """
        with self._driver.session() as session:
            session.run(
                query,
                claim_id=claim_id,
                text=text[:2000],
                source_span_id=source_span_id,
                status=status,
                confidence=confidence,
                extractor=extractor,
                extracted_at=datetime.now(UTC).isoformat(),
                entity_names=entity_names,
            ).consume()

    def find_evidence_by_entity(
        self,
        entity_name: str,
        limit: int = 20,
        access_levels: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Графовый поиск: найти все source spans и claims, упоминающие сущность."""
        if not self.available:
            return []
        access_filter = ""
        params: dict[str, Any] = {"name": entity_name, "limit": limit}
        if access_levels:
            access_filter = "AND s.access_level IN $access_levels"
            params["access_levels"] = access_levels

        query = f"""
        MATCH (e:Entity {{name: $name}})<-[:MENTIONS]-(s:SourceSpan)
        WHERE 1=1 {access_filter}
        OPTIONAL MATCH (c:Claim)-[:EVIDENCED_BY]->(s)
        OPTIONAL MATCH (d:Document)-[:HAS_SPAN]->(s)
        RETURN s.source_span_id AS source_span_id,
               s.document_id AS document_id,
               s.raw_text AS raw_text,
               s.page AS page,
               s.row_index AS row_index,
               s.column_name AS column_name,
               d.title AS title,
               d.source_type AS source_type,
               c.claim_id AS claim_id,
               c.text AS claim_text,
               c.confidence AS confidence,
               c.status AS claim_status
        LIMIT $limit
        """
        with self._driver.session() as session:
            result = session.run(query, **params)
            return [dict(record) for record in result]

    def find_related_entities(
        self,
        entity_name: str,
        max_depth: int = 2,
        limit: int = 30,
    ) -> dict[str, Any]:
        """Локальный граф: сущности в радиусе max_depth от заданной."""
        if not self.available:
            return {"nodes": [], "edges": []}
        query = """
        MATCH path = (e:Entity {name: $name})-[*1..2]-(related)
        WITH nodes(path) AS ns, relationships(path) AS rs
        UNWIND ns AS n
        WITH collect(DISTINCT n) AS nodes, rs
        UNWIND rs AS r
        WITH nodes, collect(DISTINCT r) AS edges
        RETURN nodes, edges
        LIMIT $limit
        """
        with self._driver.session() as session:
            result = session.run(query, name=entity_name, limit=limit)
            nodes: list[dict[str, Any]] = []
            edges: list[dict[str, Any]] = []
            seen_node_ids: set[str] = set()
            for record in result:
                for node in record["nodes"]:
                    node_id = dict(node).get("entity_id") or dict(node).get("source_span_id") or str(node.id)
                    if node_id in seen_node_ids:
                        continue
                    seen_node_ids.add(node_id)
                    node_dict = dict(node)
                    node_dict["_id"] = node_id
                    node_dict["_labels"] = list(node.labels)
                    nodes.append(node_dict)
                for edge in record["edges"]:
                    edges.append({
                        "start": dict(edge.start_node).get("entity_id") or str(edge.start_node.id),
                        "end": dict(edge.end_node).get("entity_id") or str(edge.end_node.id),
                        "type": edge.type,
                    })
            return {"nodes": nodes[:limit], "edges": edges[:limit]}

    def stats(self) -> dict[str, int]:
        if not self.available:
            return {"documents": 0, "spans": 0, "entities": 0, "claims": 0}
        with self._driver.session() as session:
            stats = {}
            for label in ["Document", "SourceSpan", "Entity", "Claim"]:
                result = session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt")
                stats[label.lower() + "s"] = result.single()["cnt"]
            return stats


_default_graph: KnowledgeGraph | None = None


def get_default_graph() -> KnowledgeGraph:
    global _default_graph
    if _default_graph is None:
        _default_graph = KnowledgeGraph()
    return _default_graph
