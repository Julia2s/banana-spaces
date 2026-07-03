import asyncio
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractor import extract_facts_from_text


@pytest.mark.asyncio
async def test_extract_facts():
    test_text = "В 2023 году в РФ исследовали электроэкстракцию никеля при температуре 80 °C. Метод показал высокую эффективность."
    result = await extract_facts_from_text(test_text)
    assert result is not None
    assert len(result.facts) >= 0
