from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import DocumentExtraction
from db.models import FactModel, ParameterModel


async def save_extraction_to_db(db: AsyncSession, extraction: DocumentExtraction, source_filename: str):
    for fact_data in extraction.facts:
        db_fact = FactModel(
            material=fact_data.material,
            process=fact_data.process,
            geography=fact_data.geography,
            year=fact_data.year,
            outcome=fact_data.outcome,
            confidence_level=fact_data.confidence_level,
            source_file=source_filename,
        )
        db.add(db_fact)
        await db.flush()

        for param_data in fact_data.parameters:
            db_param = ParameterModel(
                fact_id=db_fact.id,
                name=param_data.name,
                value_min=param_data.value_min,
                value_max=param_data.value_max,
                unit=param_data.unit,
            )
            db.add(db_param)

    await db.commit()
