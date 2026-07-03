import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.llm_client import ask_llm_json
from core.prompts import SQL_GENERATION_PROMPT, SYNTHESIS_PROMPT


async def get_sql_from_query(user_query: str) -> str:
    response = await ask_llm_json(system_prompt=SQL_GENERATION_PROMPT, user_text=user_query)
    try:
        return json.loads(response).get("sql_query", "")
    except Exception:
        return ""


async def execute_query(db: AsyncSession, sql_query: str) -> list:
    if not sql_query:
        return []
    result = await db.execute(text(sql_query))
    rows = result.fetchall()
    return [dict(row._mapping) for row in rows]


async def synthesize_answer(user_query: str, db_results: list) -> str:
    if not db_results:
        return "Не найдено информации по вашему запросу."

    context = str(db_results)
    response = await ask_llm_json(
        system_prompt=SYNTHESIS_PROMPT, user_text=f"Вопрос: {user_query}\nДанные из БД: {context}"
    )
    try:
        return json.loads(response).get("answer", "")
    except Exception:
        return ""


async def ask_knowledge_base(user_query: str, db: AsyncSession) -> str:
    sql_query = await get_sql_from_query(user_query)
    db_results = await execute_query(db, sql_query)
    answer = await synthesize_answer(user_query, db_results)
    return answer
