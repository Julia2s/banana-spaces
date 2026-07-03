from scientific_tangle_gateway.extractor import (
    DictionaryLoader,
    KnowledgeExtractor,
    RuleBasedExtractor,
)


SAMPLE_TEXT = "При электроэкстракции никеля оптимальная скорость циркуляции католита составляет 0.4 м/с при температуре 65 °C."


def test_dictionary_loader_loads_materials() -> None:
    loader = DictionaryLoader()
    materials = loader.materials
    names = [m["name"] for m in materials]
    assert "никель" in names
    assert "католит" in names


def test_dictionary_loader_loads_processes() -> None:
    loader = DictionaryLoader()
    processes = loader.processes
    names = [p["name"] for p in processes]
    assert "электроэкстракция" in names
    assert "циркуляция католита" in names


def test_rule_extractor_finds_entities() -> None:
    extractor = RuleBasedExtractor()
    entities = extractor.extract_entities(SAMPLE_TEXT, "span-1")
    names = {e.name for e in entities}
    assert "никель" in names
    assert "электроэкстракция" in names
    assert "католит" in names
    assert "циркуляция католита" in names
    assert all(e.source_span_id == "span-1" for e in entities)


def test_rule_extractor_finds_quantities() -> None:
    extractor = RuleBasedExtractor()
    quantities = extractor.extract_quantities(SAMPLE_TEXT, "span-1")
    assert len(quantities) >= 2

    speed_q = next((q for q in quantities if q.unit == "м/с"), None)
    assert speed_q is not None
    assert speed_q.value == 0.4
    assert speed_q.dimension == "flow_rate"
    assert speed_q.property_name == "скорость потока"

    temp_q = next((q for q in quantities if q.unit in {"°c", "c"}), None)
    assert temp_q is not None
    assert temp_q.value == 65.0


def test_rule_extractor_handles_empty_text() -> None:
    extractor = RuleBasedExtractor()
    assert extractor.extract_entities("", "span-1") == []
    assert extractor.extract_quantities("", "span-1") == []


def test_rule_extractor_aliases_work() -> None:
    extractor = RuleBasedExtractor()
    text = "Electrowinning of nickel with catholyte circulation."
    entities = extractor.extract_entities(text, "span-en")
    names = {e.name for e in entities}
    assert "электроэкстракция" in names
    assert "никель" in names


def test_knowledge_extractor_returns_result() -> None:
    extractor = KnowledgeExtractor()
    result = extractor.extract(SAMPLE_TEXT, "span-1")
    assert result.entities
    assert result.quantities
    assert result.claims


def test_knowledge_extractor_placeholder_claim_has_low_confidence() -> None:
    extractor = KnowledgeExtractor()
    result = extractor.extract("никель католит электроэкстракция", "span-short")
    if result.claims:
        claim = result.claims[0]
        assert claim.extractor == "rule"
        assert claim.status in {"candidate", "extracted"}
        assert claim.confidence <= 0.5
