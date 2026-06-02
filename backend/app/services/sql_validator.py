import sqlglot
from sqlglot import exp


FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "ATTACH", "DETACH", "COPY", "EXPORT",
    "IMPORT", "PRAGMA",
}


def _get_schema_columns(schema_context: dict) -> set[str]:
    schema_profile = schema_context.get("schema_profile", {})
    columns = schema_profile.get("columns", [])

    if isinstance(columns, list):
        return {
            column["name"]
            for column in columns
            if isinstance(column, dict) and "name" in column
        }

    if isinstance(columns, dict):
        return set(columns.keys())

    return set()


def validate_sql(sql: str, schema_context: dict) -> None:
    expected_table = schema_context["table_name"]
    valid_columns = _get_schema_columns(schema_context)

    upper_sql = sql.upper()

    if ";" in sql.strip().rstrip(";"):
        raise ValueError("Multiple SQL statements are not allowed")

    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in upper_sql:
            raise ValueError(f"Forbidden SQL keyword detected: {keyword}")

    try:
        parsed = sqlglot.parse_one(sql, read="duckdb")
    except Exception as exc:
        raise ValueError(f"Malformed SQL: {exc}")

    if not isinstance(parsed, exp.Select):
        raise ValueError("Only SELECT queries are allowed")

    if parsed.find(exp.Join):
        raise ValueError("JOIN queries are not supported yet")

    if parsed.find(exp.Subquery):
        raise ValueError("Subqueries are not supported yet")

    if parsed.find(exp.CTE):
        raise ValueError("CTEs are not supported yet")

    referenced_tables = {
        table.name
        for table in parsed.find_all(exp.Table)
    }

    if referenced_tables != {expected_table}:
        raise ValueError(
            f"Invalid table reference. Expected only table: {expected_table}"
        )

    select_aliases = {
        alias.alias
        for alias in parsed.find_all(exp.Alias)
        if alias.alias
    }

    referenced_columns = {
        column.name
        for column in parsed.find_all(exp.Column)
    }

    invalid_columns = referenced_columns - valid_columns - select_aliases

    if invalid_columns:
        raise ValueError(
            f"Invalid column reference(s): {sorted(invalid_columns)}"
        )