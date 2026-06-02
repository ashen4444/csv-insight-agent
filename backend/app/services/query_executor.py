import math
import time
from decimal import Decimal
from datetime import date, datetime
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import sqlglot
from sqlglot import exp

from app.core.config import DUCKDB_PATH


DEFAULT_LIMIT = 100
MAX_LIMIT = 100


def apply_safe_limit(sql: str) -> str:
    parsed = sqlglot.parse_one(sql)

    limit_expression = parsed.args.get("limit")

    if limit_expression is None:
        parsed.set("limit", exp.Limit(expression=exp.Literal.number(DEFAULT_LIMIT)))
        return parsed.sql(dialect="duckdb")

    current_limit = limit_expression.expression

    if isinstance(current_limit, exp.Literal):
        try:
            limit_value = int(current_limit.this)

            if limit_value > MAX_LIMIT:
                parsed.set("limit", exp.Limit(expression=exp.Literal.number(MAX_LIMIT)))
                return parsed.sql(dialect="duckdb")

        except ValueError:
            parsed.set("limit", exp.Limit(expression=exp.Literal.number(MAX_LIMIT)))
            return parsed.sql(dialect="duckdb")

    return parsed.sql(dialect="duckdb")


def serialize_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, float) and math.isnan(value):
        return None

    if isinstance(value, (np.integer,)):
        return int(value)

    if isinstance(value, (np.floating,)):
        if math.isnan(float(value)):
            return None
        return float(value)

    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    return value


def serialize_records(records: list[dict]) -> list[dict]:
    return [
        {key: serialize_value(value) for key, value in row.items()}
        for row in records
    ]


def execute_query(sql: str) -> dict:
    safe_sql = apply_safe_limit(sql)

    start_time = time.perf_counter()

    with duckdb.connect(str(DUCKDB_PATH)) as conn:
        result_df = conn.execute(safe_sql).fetchdf()

    execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

    records = result_df.to_dict(orient="records")
    serialized_results = serialize_records(records)

    return {
        "sql": safe_sql,
        "row_count": len(serialized_results),
        "execution_time_ms": execution_time_ms,
        "results": serialized_results,
    }