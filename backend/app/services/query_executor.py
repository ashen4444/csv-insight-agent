import math
import threading
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import sqlglot
from sqlglot import exp

from app.core.config import (
    DEFAULT_QUERY_LIMIT,
    DUCKDB_PATH,
    MAX_QUERY_LIMIT,
    QUERY_TIMEOUT_SECONDS,
)


def apply_safe_limit(sql: str) -> str:
    parsed = sqlglot.parse_one(sql)

    limit_expression = parsed.args.get("limit")

    if limit_expression is None:
        parsed.set(
            "limit",
            exp.Limit(expression=exp.Literal.number(DEFAULT_QUERY_LIMIT)),
        )
        return parsed.sql(dialect="duckdb")

    current_limit = limit_expression.expression

    if isinstance(current_limit, exp.Literal):
        try:
            limit_value = int(current_limit.this)

            if limit_value > MAX_QUERY_LIMIT:
                parsed.set(
                    "limit",
                    exp.Limit(expression=exp.Literal.number(MAX_QUERY_LIMIT)),
                )

        except ValueError:
            parsed.set(
                "limit",
                exp.Limit(expression=exp.Literal.number(MAX_QUERY_LIMIT)),
            )

    return parsed.sql(dialect="duckdb")


def serialize_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, float) and math.isnan(value):
        return None

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
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

    try:
        with duckdb.connect(str(DUCKDB_PATH)) as conn:
            timeout_timer = threading.Timer(
                QUERY_TIMEOUT_SECONDS,
                conn.interrupt,
            )

            timeout_timer.start()

            try:
                result_df = conn.execute(safe_sql).fetchdf()
            finally:
                timeout_timer.cancel()

    except duckdb.Error as exc:
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        raise ValueError(
            f"Query execution failed or exceeded timeout limit "
            f"of {QUERY_TIMEOUT_SECONDS} seconds. "
            f"Execution time: {execution_time_ms} ms. "
            f"Details: {exc}"
        ) from exc

    execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

    records = result_df.to_dict(orient="records")
    serialized_results = serialize_records(records)

    return {
        "sql": safe_sql,
        "row_count": len(serialized_results),
        "execution_time_ms": execution_time_ms,
        "results": serialized_results,
    }