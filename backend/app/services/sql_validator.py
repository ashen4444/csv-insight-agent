import sqlglot
from sqlglot import exp


FORBIDDEN_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "ATTACH",
    "DETACH",
    "COPY",
    "EXPORT",
    "IMPORT",
    "PRAGMA",
}


def validate_sql(sql: str) -> None:
    upper_sql = sql.upper()

    if ";" in sql.strip().rstrip(";"):
        raise ValueError("Multiple SQL statements are not allowed")

    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in upper_sql:
            raise ValueError(f"Forbidden SQL keyword detected: {keyword}")

    parsed = sqlglot.parse_one(sql)

    if not isinstance(parsed, exp.Select):
        raise ValueError("Only SELECT queries are allowed")