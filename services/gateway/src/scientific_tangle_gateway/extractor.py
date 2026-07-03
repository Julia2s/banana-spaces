"""Knowledge extractor.

Извлекает сущности, числа, единицы и связи из SourceSpan.
Двухуровневая стратегия:
1. Rule-based: точечный поиск по словарям (materials/processes/equipment).
   Быстро, детерминировано, покрывает 80% доменных терминов.
2. LLM-based: вызов YandexGPT для извлечения claims и сложных отношений.
   Только для SourceSpan с ненулевым объёмом текста, не чаще 1 запроса на чанк.

Все извлечённые факты имеют source_span_id — без него факт не валиден.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import yaml

from scientific_tangle_gateway.yandex_client import YandexClient

logger = logging.getLogger(__name__)

DICTIONARIES_DIR = Path(__file__).parent / "dictionaries"

NUMBER_PATTERN = re.compile(
    r"(?P<operator><=|>=|<|>|до|не более|не менее|около|свыше)?\s*"
    r"(?P<value>\d+(?:[\.,]\d+)?)\s*"
    r"(?P<unit>мг/л|мг/дм3|мг/дм³|°c|м/с|л/мин|м3/ч|т/сут|т/год|кг/ч|%|руб|usd|eur|k|c|ppm|g/l)?",
    flags=re.IGNORECASE,
)


@dataclass
class ExtractedEntity:
    name: str
    entity_type: str
    canonical_id: str
    mention: str
    source_span_id: str
    char_start: int
    char_end: int
    aliases: list[str] = field(default_factory=list)
    chemical_formula: str | None = None
    extractor: str = "rule"


@dataclass
class ExtractedQuantity:
    raw_text: str
    value: float
    operator: str | None
    unit: str | None
    dimension: str
    source_span_id: str
    char_start: int
    char_end: int
    property_name: str | None = None


@dataclass
class ExtractedClaim:
    claim_id: str
    text: str
    source_span_id: str
    entities: list[str]
    quantities: list[ExtractedQuantity]
    confidence: float
    status: str = "extracted"
    extractor: str = "rule"


@dataclass
class ExtractionResult:
    entities: list[ExtractedEntity] = field(default_factory=list)
    quantities: list[ExtractedQuantity] = field(default_factory=list)
    claims: list[ExtractedClaim] = field(default_factory=list)


class DictionaryLoader:
    """Загружает YAML-словари один раз, кэширует в памяти."""

    def __init__(self, dictionaries_dir: Path = DICTIONARIES_DIR) -> None:
        self.dictionaries_dir = dictionaries_dir
        self._materials: list[dict[str, Any]] = []
        self._processes: list[dict[str, Any]] = []
        self._equipment: list[dict[str, Any]] = []
        self._properties: list[dict[str, Any]] = []
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._materials = self._load_yaml("materials.yaml").get("materials", [])
        self._processes = self._load_yaml("processes.yaml").get("processes", [])
        equipment_data = self._load_yaml("equipment.yaml")
        self._equipment = equipment_data.get("equipment", [])
        self._properties = equipment_data.get("properties", [])
        self._loaded = True

    def _load_yaml(self, name: str) -> dict[str, Any]:
        path = self.dictionaries_dir / name
        if not path.exists():
            logger.warning("Словарь не найден: %s", path)
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    @property
    def materials(self) -> list[dict[str, Any]]:
        self.load()
        return self._materials

    @property
    def processes(self) -> list[dict[str, Any]]:
        self.load()
        return self._processes

    @property
    def equipment(self) -> list[dict[str, Any]]:
        self.load()
        return self._equipment

    @property
    def properties(self) -> list[dict[str, Any]]:
        self.load()
        return self._properties

    def all_entries(self) -> list[tuple[str, dict[str, Any]]]:
        """Возвращает список (entity_type, entry) для всех словарей."""
        result = []
        for entry in self.materials:
            result.append(("material", entry))
        for entry in self.processes:
            result.append(("process", entry))
        for entry in self.equipment:
            result.append(("equipment", entry))
        return result


class RuleBasedExtractor:
    """Точечный поиск сущностей из словарей в тексте."""

    def __init__(self, loader: DictionaryLoader | None = None) -> None:
        self.loader = loader or DictionaryLoader()

    def extract_entities(self, text: str, source_span_id: str) -> list[ExtractedEntity]:
        if not text:
            return []
        entities: list[ExtractedEntity] = []
        seen_spans: set[tuple[str, int, int]] = set()

        for entity_type, entry in self.loader.all_entries():
            name = entry.get("name", "").strip()
            if not name:
                continue
            aliases = [name] + [a.strip() for a in entry.get("aliases", []) if a.strip()]
            for alias in aliases:
                if len(alias) < 2:
                    continue
                pattern = re.compile(re.escape(alias), flags=re.IGNORECASE)
                for match in pattern.finditer(text):
                    key = (entry["name"], match.start(), match.end())
                    if key in seen_spans:
                        continue
                    seen_spans.add(key)
                    canonical_id = str(uuid5(NAMESPACE_URL, f"{entity_type}:{entry['name'].lower()}"))
                    entities.append(
                        ExtractedEntity(
                            name=entry["name"],
                            entity_type=entity_type,
                            canonical_id=canonical_id,
                            mention=match.group(0),
                            source_span_id=source_span_id,
                            char_start=match.start(),
                            char_end=match.end(),
                            aliases=entry.get("aliases", []),
                            chemical_formula=entry.get("chemical_formula"),
                            extractor="rule",
                        )
                    )
        return entities

    def extract_quantities(self, text: str, source_span_id: str) -> list[ExtractedQuantity]:
        if not text:
            return []
        quantities: list[ExtractedQuantity] = []
        for match in NUMBER_PATTERN.finditer(text):
            raw = match.group(0).strip()
            value_str = match.group("value").replace(",", ".")
            try:
                value = float(value_str)
            except ValueError:
                continue
            operator = (match.group("operator") or "").strip().lower() or None
            unit = (match.group("unit") or "").strip().lower() or None
            dimension = self._dimension_for_unit(unit)
            property_name = self._guess_property_name(text, match.start(), unit)
            quantities.append(
                ExtractedQuantity(
                    raw_text=raw,
                    value=value,
                    operator=operator,
                    unit=unit,
                    dimension=dimension,
                    source_span_id=source_span_id,
                    char_start=match.start(),
                    char_end=match.end(),
                    property_name=property_name,
                )
            )
        return quantities

    def _dimension_for_unit(self, unit: str | None) -> str:
        if not unit:
            return "generic"
        if unit in {"мг/л", "мг/дм3", "мг/дм³", "ppm", "g/l"}:
            return "concentration"
        if unit in {"°c", "c", "k"}:
            return "temperature"
        if unit in {"м/с", "m/s", "л/мин", "l/min", "м3/ч", "m3/h"}:
            return "flow_rate"
        if unit in {"т/сут", "t/day", "т/год", "t/year", "кг/ч"}:
            return "capacity"
        if unit == "%":
            return "percent"
        if unit in {"руб", "usd", "eur"}:
            return "currency"
        return "generic"

    def _guess_property_name(self, text: str, pos: int, unit: str | None) -> str | None:
        """Пытается определить, к какому свойству относится число, по контексту."""
        if not unit:
            return None
        context = text[max(0, pos - 40) : pos].lower()
        if unit in {"мг/л", "мг/дм3", "мг/дм³", "ppm", "g/l"}:
            if "сухой" in context or "остаток" in context or "tds" in context:
                return "сухой остаток"
            return "концентрация"
        if unit in {"°c", "c", "k"}:
            return "температура"
        if unit in {"м/с", "m/s", "л/мин", "l/min", "м3/ч", "m3/h"}:
            return "скорость потока"
        if unit in {"т/сут", "t/day", "т/год", "t/year", "кг/ч"}:
            return "производительность"
        if unit == "%":
            if "выход" in context or "извлечение" in context or "recovery" in context:
                return "выход металла"
            return None
        return None


class LLMClaimExtractor:
    """Извлечение claims через YandexGPT. Опционально — fallback на None."""

    EXTRACTION_PROMPT = """Ты — аналитик горно-металлургических исследований.
Извлеки из текста факты (claims) о технологических процессах, материалах, оборудовании и числовых параметрах.
Каждый факт должен быть самодостаточным утверждением, которое можно проверить по тексту.

Верни строго JSON:
{
  "claims": [
    {
      "text": "При электроэкстракции никеля оптимальная скорость циркуляции католита составляет 0.3-0.5 м/с",
      "entities": ["электроэкстракция", "никель", "католит"],
      "confidence": 0.9
    }
  ]
}

Если фактов нет — верни {"claims": []}.
Не выдумывай факты, которых нет в тексте.
Текст:
"""

    def __init__(self, client: YandexClient | None = None) -> None:
        self.client = client or YandexClient()

    def extract_claims(self, text: str, source_span_id: str) -> list[ExtractedClaim]:
        if not text or len(text) < 50:
            return []
        if not self.client.is_configured:
            return []

        try:
            data = self.client.chat_json(
                system_prompt=self.EXTRACTION_PROMPT,
                user_prompt=text[:4000],
                temperature=0.1,
                max_tokens=1500,
            )
        except Exception as error:
            logger.warning("LLM extraction failed: %s", error)
            return []

        claims: list[ExtractedClaim] = []
        for item in data.get("claims", []):
            text_value = item.get("text", "").strip()
            if not text_value:
                continue
            claim_id = str(uuid5(NAMESPACE_URL, f"{source_span_id}:{text_value}"))
            claims.append(
                ExtractedClaim(
                    claim_id=claim_id,
                    text=text_value,
                    source_span_id=source_span_id,
                    entities=item.get("entities", []),
                    quantities=[],
                    confidence=float(item.get("confidence", 0.5)),
                    extractor="llm",
                )
            )
        return claims


class KnowledgeExtractor:
    """Оркестрирует rule-based и LLM extraction."""

    def __init__(
        self,
        rule_extractor: RuleBasedExtractor | None = None,
        llm_extractor: LLMClaimExtractor | None = None,
    ) -> None:
        self.rule_extractor = rule_extractor or RuleBasedExtractor()
        self.llm_extractor = llm_extractor or LLMClaimExtractor()

    def extract(self, text: str, source_span_id: str) -> ExtractionResult:
        entities = self.rule_extractor.extract_entities(text, source_span_id)
        quantities = self.rule_extractor.extract_quantities(text, source_span_id)
        claims = self.llm_extractor.extract_claims(text, source_span_id)

        if not claims and entities:
            placeholder = self._build_placeholder_claim(entities, quantities, source_span_id)
            if placeholder is not None:
                claims.append(placeholder)

        return ExtractionResult(entities=entities, quantities=quantities, claims=claims)

    def _build_placeholder_claim(
        self,
        entities: list[ExtractedEntity],
        quantities: list[ExtractedQuantity],
        source_span_id: str,
    ) -> ExtractedClaim | None:
        if not entities:
            return None
        names = sorted({e.name for e in entities})[:3]
        text = f"Источник упоминает: {', '.join(names)}"
        if quantities:
            q_text = "; ".join(f"{q.value} {q.unit or ''}".strip() for q in quantities[:3])
            text += f"; числовые параметры: {q_text}"
        claim_id = str(uuid5(NAMESPACE_URL, f"{source_span_id}:placeholder"))
        return ExtractedClaim(
            claim_id=claim_id,
            text=text,
            source_span_id=source_span_id,
            entities=names,
            quantities=quantities,
            confidence=0.4,
            status="candidate",
            extractor="rule",
        )
