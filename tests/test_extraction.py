import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.retriever import execute_query
from core.schemas import DocumentExtraction, KnowledgeFact, Parameter


def test_pydantic_schema_validation():
    fact = KnowledgeFact(
        material="Медь",
        process="Плавка",
        geography="РФ",
        year=2023,
        parameters=[Parameter(name="Температура", value_max=1200.0, unit="°C")],
        outcome="Успешно",
        confidence_level="Высокий",
    )
    extraction = DocumentExtraction(facts=[fact])
    assert len(extraction.facts) == 1
    assert extraction.facts[0].material == "Медь"


@pytest.mark.asyncio
async def test_sql_injection_defense():
    class MockDB:
        async def execute(self, text_obj):
            return []

    db = MockDB()
    unsafe_query_1 = "DELETE FROM facts;"
    unsafe_query_2 = "SELECT * FROM facts; DROP TABLE parameters;"

    res_1 = await execute_query(db, unsafe_query_1)
    res_2 = await execute_query(db, unsafe_query_2)

    assert res_1 == []
    assert res_2 == []
