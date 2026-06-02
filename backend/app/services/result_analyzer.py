from datetime import date, datetime
from decimal import Decimal
from typing import Any


NUMERIC_TYPES = (int, float, Decimal)
DATE_TYPES = (date, datetime)

MAX_CHART_ROWS = 30

TABLE_ONLY_KEYWORDS = {
    "list",
    "first",
    "rows",
    "row",
    "records",
    "record",
    "data",
    "table",
}


def analyze_results(
    results: list[dict[str, Any]],
    question: str | None = None,
) -> dict[str, Any]:
    if _is_table_only_question(question):
        return _analysis(
            result_type="raw_table_preview",
            recommended_visualization="table",
            is_visualizable=False,
            x_axis=None,
            y_axis=None,
            confidence=0.95,
            reason="Question asks for raw rows or table-style output.",
        )

    if not results:
        return _analysis(
            result_type="empty",
            recommended_visualization="table",
            is_visualizable=False,
            x_axis=None,
            y_axis=None,
            confidence=1.0,
            reason="Result set is empty.",
        )

    columns = list(results[0].keys())

    if len(columns) == 0:
        return _analysis(
            result_type="empty",
            recommended_visualization="table",
            is_visualizable=False,
            x_axis=None,
            y_axis=None,
            confidence=1.0,
            reason="No columns detected in the result.",
        )

    numeric_columns = [
        column for column in columns
        if _is_numeric_column(results, column)
    ]

    datetime_columns = [
        column for column in columns
        if _is_datetime_column(results, column)
    ]

    categorical_columns = [
        column for column in columns
        if column not in numeric_columns and column not in datetime_columns
    ]

    row_count = len(results)

    if row_count == 1 and len(columns) == 1 and len(numeric_columns) == 1:
        return _analysis(
            result_type="single_metric",
            recommended_visualization="metric_card",
            is_visualizable=True,
            x_axis=None,
            y_axis=numeric_columns[0],
            confidence=0.98,
            reason="Detected a single numeric value.",
        )

    if len(datetime_columns) >= 1 and len(numeric_columns) >= 1:
        return _analysis(
            result_type="time_series",
            recommended_visualization="line_chart",
            is_visualizable=True,
            x_axis=datetime_columns[0],
            y_axis=numeric_columns[0],
            confidence=0.95,
            reason="Detected a date/time column and a numeric column.",
        )

    if row_count > MAX_CHART_ROWS:
        return _analysis(
            result_type="large_tabular_result",
            recommended_visualization="table",
            is_visualizable=False,
            x_axis=None,
            y_axis=None,
            confidence=0.85,
            reason="Result has too many rows for a clear default chart.",
        )

    if len(categorical_columns) == 1 and len(numeric_columns) == 1:
        return _analysis(
            result_type="categorical_numeric",
            recommended_visualization="bar_chart",
            is_visualizable=True,
            x_axis=categorical_columns[0],
            y_axis=numeric_columns[0],
            confidence=0.92,
            reason="Detected one categorical column and one numeric column.",
        )

    if len(numeric_columns) >= 2 and row_count > 1:
        return _analysis(
            result_type="numeric_relationship",
            recommended_visualization="scatter_plot",
            is_visualizable=True,
            x_axis=numeric_columns[0],
            y_axis=numeric_columns[1],
            confidence=0.90,
            reason="Detected two numeric columns across multiple rows.",
        )

    return _analysis(
        result_type="tabular",
        recommended_visualization="table",
        is_visualizable=False,
        x_axis=None,
        y_axis=None,
        confidence=0.60,
        reason="Result is best represented as a table.",
    )


def _analysis(
    result_type: str,
    recommended_visualization: str,
    is_visualizable: bool,
    x_axis: str | None,
    y_axis: str | None,
    confidence: float,
    reason: str,
) -> dict[str, Any]:
    return {
        "result_type": result_type,
        "recommended_visualization": recommended_visualization,
        "is_visualizable": is_visualizable,
        "x_axis": x_axis,
        "y_axis": y_axis,
        "confidence": confidence,
        "reason": reason,
    }


def _is_table_only_question(question: str | None) -> bool:
    if question is None:
        return False

    question_lower = question.lower()

    return any(
        keyword in question_lower
        for keyword in TABLE_ONLY_KEYWORDS
    )


def _is_numeric_column(results: list[dict[str, Any]], column: str) -> bool:
    values = _non_empty_values(results, column)

    if not values:
        return False

    return all(
        isinstance(value, NUMERIC_TYPES) and not isinstance(value, bool)
        for value in values
    )


def _is_datetime_column(results: list[dict[str, Any]], column: str) -> bool:
    values = _non_empty_values(results, column)

    if not values:
        return False

    return all(
        isinstance(value, DATE_TYPES) or _looks_like_date_string(value)
        for value in values
    )


def _non_empty_values(results: list[dict[str, Any]], column: str) -> list[Any]:
    return [
        row.get(column)
        for row in results
        if row.get(column) is not None
    ]


def _looks_like_date_string(value: Any) -> bool:
    if not isinstance(value, str):
        return False

    date_formats = [
        "%Y-%m-%d",
        "%Y-%m",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
    ]

    for date_format in date_formats:
        try:
            datetime.strptime(value, date_format)
            return True
        except ValueError:
            continue

    return False