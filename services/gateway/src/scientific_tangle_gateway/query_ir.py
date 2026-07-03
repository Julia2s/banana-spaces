import re
from uuid import uuid4

from scientific_tangle_gateway.schemas import (
    AccessLevel,
    QueryAccessScopePayload,
    QueryEntityPayload,
    QueryIRPayload,
    QueryNumericConstraintPayload,
    QueryTimeRangePayload,
    UserRole,
)

ROLE_ACCESS_LEVELS: dict[UserRole, list[AccessLevel]] = {
    "admin": ["public", "internal", "confidential", "restricted"],
    "researcher": ["public", "internal", "confidential"],
    "analyst": ["public", "internal"],
    "manager": ["public", "internal"],
    "external_partner": ["public"],
}

ENTITY_STOPWORDS = {
    "что",
    "как",
    "где",
    "какие",
    "какой",
    "какая",
    "какое",
    "по",
    "для",
    "или",
    "при",
    "над",
    "под",
    "без",
    "это",
    "все",
}

GEO_TOKENS = {
    "россия",
    "рф",
    "зарубеж",
    "европа",
    "китай",
    "чили",
    "снг",
    "сша",
}

SOURCE_TYPE_TOKENS = {
    "статья": "article",
    "журнал": "journal",
    "конференц": "conference",
    "патент": "patent",
    "отчет": "report",
    "отчёт": "report",
    "стандарт": "standard",
}

ANALYSIS_FLAGS = {
    "таблиц": "need_table",
    "граф": "need_graph",
    "пробел": "need_gaps",
    "gap": "need_gaps",
    "конфликт": "need_conflicts",
    "эксперт": "need_experts",
    "экспорт": "need_export",
}

NUMERIC_PATTERN = re.compile(
    r"(?P<operator><=|>=|<|>|до|не более|не менее|около)?\s*"
    r"(?P<value>\d+(?:[\.,]\d+)?)\s*(?P<unit>мг/л|мг/дм3|мг/дм³|°c|c|%|кг/т)?",
    flags=re.IGNORECASE,
)
YEAR_RANGE_PATTERN = re.compile(r"(20\d{2})\s*[-–]\s*(20\d{2})")


class QueryIRBuilder:
    def build(self, question: str, role: UserRole) -> QueryIRPayload:
        question_normalized = " ".join(question.split())
        entities = self._extract_entities(question_normalized)
        numeric_constraints = self._extract_numeric_constraints(question_normalized)
        geo_scope = self._extract_geo_scope(question_normalized)
        source_types = self._extract_source_types(question_normalized)
        analysis_flags = self._extract_analysis_flags(question_normalized)
        time_range = self._extract_time_range(question_normalized)
        goal = self._derive_goal(question_normalized)

        return QueryIRPayload(
            query_id=str(uuid4()),
            question=question_normalized,
            goal=goal,
            entities=entities,
            numeric_constraints=numeric_constraints,
            geo_scope=geo_scope,
            time_range=time_range,
            source_types=source_types,
            access_scope=QueryAccessScopePayload(
                role=role,
                allowed_access_levels=ROLE_ACCESS_LEVELS[role],
            ),
            analysis_flags=analysis_flags,
        )

    def _extract_entities(self, question: str) -> list[QueryEntityPayload]:
        tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9\+\-]{3,}", question)
        entities: list[QueryEntityPayload] = []
        seen: set[str] = set()
        for token in tokens:
            normalized = token.lower()
            if normalized in ENTITY_STOPWORDS:
                continue
            if normalized.isdigit():
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            entities.append(QueryEntityPayload(mention=token))
        return entities[:20]

    def _extract_numeric_constraints(self, question: str) -> list[QueryNumericConstraintPayload]:
        constraints: list[QueryNumericConstraintPayload] = []
        for match in NUMERIC_PATTERN.finditer(question):
            value = float(match.group("value").replace(",", "."))
            operator = (match.group("operator") or "").strip().lower() or None
            unit = (match.group("unit") or "").strip().lower() or None
            min_value = None
            max_value = None
            if operator in {"<", "<=", "до", "не более"}:
                max_value = value
            elif operator in {">", ">=", "не менее"}:
                min_value = value
            else:
                min_value = value
                max_value = value

            dimension = "generic"
            if unit in {"мг/л", "мг/дм3", "мг/дм³"}:
                dimension = "concentration"
            elif unit in {"°c", "c"}:
                dimension = "temperature"
            elif unit == "%":
                dimension = "percent"

            constraints.append(
                QueryNumericConstraintPayload(
                    raw_text=match.group(0).strip(),
                    operator=operator,
                    min=min_value,
                    max=max_value,
                    unit=unit,
                    dimension=dimension,
                )
            )
        return constraints

    def _extract_geo_scope(self, question: str) -> list[str]:
        lowered = question.lower()
        geo_scope = [token for token in GEO_TOKENS if token in lowered]
        return geo_scope

    def _extract_source_types(self, question: str) -> list[str]:
        lowered = question.lower()
        source_types = []
        for token, source_type in SOURCE_TYPE_TOKENS.items():
            if token in lowered and source_type not in source_types:
                source_types.append(source_type)
        return source_types

    def _extract_analysis_flags(self, question: str) -> list[str]:
        lowered = question.lower()
        flags = []
        for token, flag in ANALYSIS_FLAGS.items():
            if token in lowered and flag not in flags:
                flags.append(flag)
        return flags

    def _extract_time_range(self, question: str) -> QueryTimeRangePayload | None:
        lowered = question.lower()
        if "последние 5 лет" in lowered or "последние пять лет" in lowered:
            return QueryTimeRangePayload(from_date="2021-01-01", to_date=None)
        if "последний год" in lowered:
            return QueryTimeRangePayload(from_date="2025-01-01", to_date=None)
        if "последние 10 лет" in lowered:
            return QueryTimeRangePayload(from_date="2016-01-01", to_date=None)

        match = YEAR_RANGE_PATTERN.search(lowered)
        if match is None:
            return None
        return QueryTimeRangePayload(
            from_date=f"{match.group(1)}-01-01",
            to_date=f"{match.group(2)}-12-31",
        )

    def _derive_goal(self, question: str) -> str:
        lowered = question.lower()
        if "сравн" in lowered:
            return "compare_methods"
        if "оптималь" in lowered:
            return "find_optimal_value"
        if "найд" in lowered or "какие" in lowered:
            return "find_evidence"
        return "research_query"
