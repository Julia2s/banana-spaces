from scientific_tangle_gateway.query_ir import QueryIRBuilder


def test_query_ir_extracts_geo_russia() -> None:
    builder = QueryIRBuilder()
    qir = builder.build(
        question="Какие способы применялись в России и за рубежом?",
        role="researcher",
    )
    assert "россия" in qir.geo_scope
    assert "зарубеж" in qir.geo_scope


def test_query_ir_extracts_source_types() -> None:
    builder = QueryIRBuilder()
    qir = builder.build(
        question="Найди статьи и патенты по теме",
        role="researcher",
    )
    assert "article" in qir.source_types
    assert "patent" in qir.source_types


def test_query_ir_extracts_numeric_constraint_max() -> None:
    builder = QueryIRBuilder()
    qir = builder.build(
        question="Найди методы с сухим остатком не более 1000 мг/дм³",
        role="researcher",
    )
    assert any(c.max == 1000.0 for c in qir.numeric_constraints)


def test_query_ir_role_access_researcher() -> None:
    builder = QueryIRBuilder()
    qir = builder.build(
        question="тест",
        role="researcher",
    )
    assert "public" in qir.access_scope.allowed_access_levels
    assert "internal" in qir.access_scope.allowed_access_levels
    assert "confidential" in qir.access_scope.allowed_access_levels
    assert "restricted" not in qir.access_scope.allowed_access_levels


def test_query_ir_role_access_external_partner() -> None:
    builder = QueryIRBuilder()
    qir = builder.build(
        question="тест",
        role="external_partner",
    )
    assert qir.access_scope.allowed_access_levels == ["public"]


def test_query_ir_goal_compare() -> None:
    builder = QueryIRBuilder()
    qir = builder.build(
        question="Сравни обратный осмос и нанофильтрацию",
        role="researcher",
    )
    assert qir.goal == "compare_methods"


def test_query_ir_goal_optimal() -> None:
    builder = QueryIRBuilder()
    qir = builder.build(
        question="Какая оптимальная скорость потока?",
        role="researcher",
    )
    assert qir.goal == "find_optimal_value"
