# backend/app/prompts/sql_generation_prompt.py

from typing import Dict, Any, List


def build_sql_generation_prompt(
    table_name: str,
    schema_profile: Dict[str, Any],
    question: str,
) -> str:
    columns = schema_profile.get("columns", [])

    column_lines = _format_columns(columns)

    return f"""
You are a DuckDB SQL generation assistant.

Your task is to generate a single safe SQL query for the user's question.

STRICT RULES:
- Generate only DuckDB-compatible SQL.
- Generate only one SELECT statement.
- Do not generate INSERT, UPDATE, DELETE, DROP, ALTER, ATTACH, PRAGMA, CREATE, or COPY.
- Do not use multiple SQL statements.
- Use only the provided table name.
- Use only the provided column names.
- Do not invent columns.
- Do not explain anything.
- Do not use markdown.
- Return only the SQL query.

TABLE:
"{table_name}"

AVAILABLE COLUMNS:
{column_lines}

USER QUESTION:
{question}

Return only the SQL query.
""".strip()


def _format_columns(columns: List[Dict[str, Any]]) -> str:
    if not columns:
        return "- No column metadata available"

    lines = []

    for column in columns:
        name = column.get("name")
        dtype = column.get("type") or column.get("inferred_type") or "UNKNOWN"
        null_count = column.get("null_count", "UNKNOWN")
        unique_count = column.get("unique_count", "UNKNOWN")

        lines.append(
            f'- "{name}" ({dtype}) | null_count={null_count} | unique_count={unique_count}'
        )

    return "\n".join(lines)