from datetime import date, datetime
from decimal import Decimal
from typing import Any


NUMERIC_TYPES = (int, float, Decimal)
DATE_TYPES = (date, datetime)


def analyze_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "result_type": "empty",
            "recommended_visualization": "table",
            "x_axis": None,
            "y_axis": None,
            "reason": "Result set is empty.",
        }

    columns = list(results[0].keys())

    if len(columns) == 0:
        return {
            "result_type": "empty",
            "recommended_visualization": "table",
            "x_axis": None,
            "y_axis": None,
            "reason": "No columns detected in the result.",
        }

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
        return {
            "result_type": "single_metric",
            "recommended_visualization": "metric_card",
            "x_axis": None,
            "y_axis": numeric_columns[0],
            "reason": "Detected a single numeric value.",
        }

    if len(datetime_columns) >= 1 and len(numeric_columns) >= 1:
        return {
            "result_type": "time_series",
            "recommended_visualization": "line_chart",
            "x_axis": datetime_columns[0],
            "y_axis": numeric_columns[0],
            "reason": "Detected a date/time column and a numeric column.",
        }

    if len(categorical_columns) == 1 and len(numeric_columns) == 1:
        return {
            "result_type": "categorical_numeric",
            "recommended_visualization": "bar_chart",
            "x_axis": categorical_columns[0],
            "y_axis": numeric_columns[0],
            "reason": "Detected one categorical column and one numeric column.",
        }

    if len(numeric_columns) >= 2 and row_count > 1:
        return {
            "result_type": "numeric_relationship",
            "recommended_visualization": "scatter_plot",
            "x_axis": numeric_columns[0],
            "y_axis": numeric_columns[1],
            "reason": "Detected two numeric columns across multiple rows.",
        }

    return {
        "result_type": "tabular",
        "recommended_visualization": "table",
        "x_axis": None,
        "y_axis": None,
        "reason": "Result is best represented as a table.",
    }


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