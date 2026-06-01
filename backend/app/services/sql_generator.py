# backend/app/services/sql_generator.py

from typing import Any, Dict

from app.prompts.sql_generation_prompt import build_sql_generation_prompt
from app.services.llm_client import generate_text


def generate_sql_from_question(
    table_name: str,
    schema_profile: Dict[str, Any],
    question: str,
) -> str:
    prompt = build_sql_generation_prompt(
        table_name=table_name,
        schema_profile=schema_profile,
        question=question,
    )

    generated_sql = generate_text(prompt)

    return _clean_generated_sql(generated_sql)


def _clean_generated_sql(generated_sql: str) -> str:
    sql = generated_sql.strip()

    if sql.startswith("```sql"):
        sql = sql.removeprefix("```sql").strip()

    if sql.startswith("```"):
        sql = sql.removeprefix("```").strip()

    if sql.endswith("```"):
        sql = sql.removesuffix("```").strip()

    return sql