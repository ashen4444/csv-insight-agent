# backend/app/services/data_quality_evaluator.py

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from app.services.result_analyzer import analyze_results


@dataclass(frozen=True)
class DataQualityEvaluatorConfig:
    large_result_set_threshold: int = 100
    max_visualization_rows: int = 30

    result_null_warning_threshold: float = 20.0
    result_null_critical_threshold: float = 70.0

    dataset_null_warning_threshold: float = 30.0
    dataset_null_critical_threshold: float = 70.0

    high_cardinality_unique_threshold: int = 30
    high_cardinality_ratio_threshold: float = 0.80


def evaluate_data_quality(
    *,
    dataset_id: str,
    question: str,
    sql: str | None,
    results: list[dict[str, Any]],
    row_count: int,
    schema_context: dict[str, Any],
    execution_time_ms: float | None = None,
    config: DataQualityEvaluatorConfig | None = None,
) -> dict[str, Any]:
    """
    Deterministic data-quality evaluator.

    This service does not clean, mutate, rewrite, or modify data.
    It only evaluates the executed query result and trusted dataset metadata.
    """

    config = config or DataQualityEvaluatorConfig()

    schema_profile = schema_context.get("schema_profile", {})
    dataset_profile = schema_profile.get("dataset", {})

    dataset_row_count = _safe_int(
        schema_context.get("row_count"),
        fallback=_safe_int(dataset_profile.get("row_count"), fallback=0),
    )
    dataset_column_count = _safe_int(
        schema_context.get("column_count"),
        fallback=_safe_int(dataset_profile.get("column_count"), fallback=0),
    )

    result_columns = _get_result_columns(results)
    profile_columns_by_name = _profile_columns_by_name(schema_profile)

    result_analysis = analyze_results(
        results=results,
        question=question,
        visualization_intent=None,
    )

    warnings: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    if row_count == 0 or not results:
        _add_warning(
            warnings,
            warning_type="empty_result",
            severity="critical",
            message="The executed query returned no rows.",
            recommendation=(
                "Check whether the filters are too restrictive or ask a broader question."
            ),
            metadata={
                "row_count": row_count,
            },
        )
        _add_recommendation(
            recommendations,
            recommendation_type="adjust_query_filters",
            priority="high",
            message=(
                "Try relaxing the query condition, removing filters, or asking for "
                "a broader summary."
            ),
        )

        return _build_response(
            quality_status="quality_failed",
            is_result_usable=False,
            is_result_empty=True,
            row_count=row_count,
            warnings=warnings,
            recommendations=recommendations,
            result_columns=result_columns,
            result_analysis=result_analysis,
            dataset_row_count=dataset_row_count,
            dataset_column_count=dataset_column_count,
            execution_time_ms=execution_time_ms,
            config=config,
            schema_context=schema_context,
        )

    if _has_inconsistent_result_shape(results):
        _add_warning(
            warnings,
            warning_type="invalid_result_shape",
            severity="critical",
            message=(
                "The query result rows do not share the same column structure."
            ),
            recommendation=(
                "Re-run the query or inspect the query execution layer before "
                "formatting this result."
            ),
            metadata={
                "row_count": row_count,
                "detected_columns": result_columns,
            },
        )
        _add_recommendation(
            recommendations,
            recommendation_type="inspect_query_result_shape",
            priority="high",
            message=(
                "Ensure every result row has the same set of columns before "
                "passing the result to downstream agents."
            ),
        )

        return _build_response(
            quality_status="quality_failed",
            is_result_usable=False,
            is_result_empty=False,
            row_count=row_count,
            warnings=warnings,
            recommendations=recommendations,
            result_columns=result_columns,
            result_analysis=result_analysis,
            dataset_row_count=dataset_row_count,
            dataset_column_count=dataset_column_count,
            execution_time_ms=execution_time_ms,
            config=config,
            schema_context=schema_context,
        )

    if row_count >= config.large_result_set_threshold:
        _add_warning(
            warnings,
            warning_type="large_result_set",
            severity="warning",
            message=(
                "The query result is large and may be difficult to present clearly "
                "in a final answer."
            ),
            recommendation=(
                "Consider summarising, grouping, filtering, or limiting the result."
            ),
            metadata={
                "row_count": row_count,
                "large_result_set_threshold": config.large_result_set_threshold,
            },
        )
        _add_recommendation(
            recommendations,
            recommendation_type="summarize_or_filter_result",
            priority="medium",
            message=(
                "For readability, consider asking for a grouped summary, top-N result, "
                "or filtered result."
            ),
        )

    if row_count > config.max_visualization_rows:
        _add_warning(
            warnings,
            warning_type="visualization_not_recommended",
            severity="warning",
            message=(
                "The result has too many rows for a clear default chart."
            ),
            recommendation=(
                "Use aggregation, filtering, or a top-N query before chart generation."
            ),
            metadata={
                "row_count": row_count,
                "max_visualization_rows": config.max_visualization_rows,
            },
        )

    elif result_analysis.get("is_visualizable") is not True:
        _add_warning(
            warnings,
            warning_type="visualization_not_recommended",
            severity="info",
            message=(
                "The result is usable for answering, but it is not a strong "
                "candidate for chart generation."
            ),
            recommendation=(
                "Use a table response unless the user explicitly requests a chart."
            ),
            metadata={
                "recommended_visualization": result_analysis.get(
                    "recommended_visualization"
                ),
                "result_type": result_analysis.get("result_type"),
                "reason": result_analysis.get("reason"),
            },
        )

    _add_result_null_warnings(
        warnings=warnings,
        recommendations=recommendations,
        results=results,
        result_columns=result_columns,
        config=config,
    )

    _add_dataset_null_warnings(
        warnings=warnings,
        recommendations=recommendations,
        result_columns=result_columns,
        profile_columns_by_name=profile_columns_by_name,
        config=config,
    )

    _add_high_cardinality_warnings(
        warnings=warnings,
        recommendations=recommendations,
        result_columns=result_columns,
        profile_columns_by_name=profile_columns_by_name,
        dataset_row_count=dataset_row_count,
        config=config,
    )

    _add_duplicate_warnings(
        warnings=warnings,
        recommendations=recommendations,
        results=results,
        schema_profile=schema_profile,
    )

    blocking_warning_types = {
        "empty_result",
        "invalid_result_shape",
    }

    if any(
        warning["warning_type"] in blocking_warning_types
        for warning in warnings
    ):
        quality_status = "quality_failed"
        is_result_usable = False
    elif warnings:
        quality_status = "quality_warning"
        is_result_usable = True
    else:
        quality_status = "quality_passed"
        is_result_usable = True

    return _build_response(
        quality_status=quality_status,
        is_result_usable=is_result_usable,
        is_result_empty=False,
        row_count=row_count,
        warnings=warnings,
        recommendations=recommendations,
        result_columns=result_columns,
        result_analysis=result_analysis,
        dataset_row_count=dataset_row_count,
        dataset_column_count=dataset_column_count,
        execution_time_ms=execution_time_ms,
        config=config,
        schema_context=schema_context,
    )


def _build_response(
    *,
    quality_status: str,
    is_result_usable: bool,
    is_result_empty: bool,
    row_count: int,
    warnings: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    result_columns: list[str],
    result_analysis: dict[str, Any],
    dataset_row_count: int,
    dataset_column_count: int,
    execution_time_ms: float | None,
    config: DataQualityEvaluatorConfig,
    schema_context: dict[str, Any],
) -> dict[str, Any]:
    has_null_warnings = any(
        warning["warning_type"] in {
            "result_null_values_detected",
            "null_heavy_column",
        }
        for warning in warnings
    )

    has_duplicate_warnings = any(
        "duplicate" in warning["warning_type"]
        for warning in warnings
    )

    has_visualization_warnings = any(
        warning["warning_type"] == "visualization_not_recommended"
        for warning in warnings
    )

    is_result_too_large = any(
        warning["warning_type"] == "large_result_set"
        for warning in warnings
    )

    return {
        "quality_status": quality_status,
        "is_result_usable": is_result_usable,
        "is_result_empty": is_result_empty,
        "is_result_too_large": is_result_too_large,
        "has_null_warnings": has_null_warnings,
        "has_duplicate_warnings": has_duplicate_warnings,
        "has_visualization_warnings": has_visualization_warnings,
        "row_count": row_count,
        "warnings": warnings,
        "recommendations": recommendations,
        "metadata": {
            "service": "evaluate_data_quality",
            "dataset_id": schema_context.get("dataset_id"),
            "table_name": schema_context.get("table_name"),
            "dataset_row_count": dataset_row_count,
            "dataset_column_count": dataset_column_count,
            "result_columns": result_columns,
            "result_column_count": len(result_columns),
            "result_analysis": result_analysis,
            "execution_time_ms": execution_time_ms,
            "warning_count": len(warnings),
            "recommendation_count": len(recommendations),
            "thresholds": asdict(config),
        },
    }


def _add_result_null_warnings(
    *,
    warnings: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    results: list[dict[str, Any]],
    result_columns: list[str],
    config: DataQualityEvaluatorConfig,
) -> None:
    row_count = len(results)

    if row_count == 0:
        return

    for column in result_columns:
        null_count = sum(
            1
            for row in results
            if row.get(column) is None
        )
        null_percentage = round((null_count / row_count) * 100, 2)

        if null_percentage < config.result_null_warning_threshold:
            continue

        severity = (
            "critical"
            if null_percentage >= config.result_null_critical_threshold
            else "warning"
        )

        _add_warning(
            warnings,
            warning_type="result_null_values_detected",
            severity=severity,
            message=(
                f"The result column '{column}' contains missing values."
            ),
            column=column,
            recommendation=(
                "Mention missing values in the final answer and avoid using this "
                "column for charts without handling nulls."
            ),
            metadata={
                "null_count": null_count,
                "row_count": row_count,
                "null_percentage": null_percentage,
            },
        )
        _add_recommendation(
            recommendations,
            recommendation_type="handle_missing_result_values",
            priority="medium",
            message=(
                f"Consider excluding, filtering, or clearly explaining missing "
                f"values in '{column}'."
            ),
            column=column,
        )


def _add_dataset_null_warnings(
    *,
    warnings: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    result_columns: list[str],
    profile_columns_by_name: dict[str, dict[str, Any]],
    config: DataQualityEvaluatorConfig,
) -> None:
    for column in result_columns:
        column_profile = profile_columns_by_name.get(column)

        if column_profile is None:
            continue

        null_percentage = _safe_float(
            column_profile.get("null_percentage"),
            fallback=0.0,
        )

        if null_percentage < config.dataset_null_warning_threshold:
            continue

        severity = (
            "critical"
            if null_percentage >= config.dataset_null_critical_threshold
            else "warning"
        )

        _add_warning(
            warnings,
            warning_type="null_heavy_column",
            severity=severity,
            message=(
                f"The source dataset column '{column}' has a high missing-value "
                f"percentage."
            ),
            column=column,
            recommendation=(
                "Warn the user that analysis involving this column may be affected "
                "by missing values."
            ),
            metadata={
                "null_count": column_profile.get("null_count"),
                "non_null_count": column_profile.get("non_null_count"),
                "null_percentage": null_percentage,
            },
        )
        _add_recommendation(
            recommendations,
            recommendation_type="review_missing_source_values",
            priority="medium",
            message=(
                f"Review missing values in '{column}' before relying on this field "
                f"for final conclusions."
            ),
            column=column,
        )


def _add_high_cardinality_warnings(
    *,
    warnings: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    result_columns: list[str],
    profile_columns_by_name: dict[str, dict[str, Any]],
    dataset_row_count: int,
    config: DataQualityEvaluatorConfig,
) -> None:
    if dataset_row_count <= 0:
        return

    for column in result_columns:
        column_profile = profile_columns_by_name.get(column)

        if column_profile is None:
            continue

        inferred_type = str(
            column_profile.get("inferred_type", "")
        ).lower()

        if inferred_type not in {"text", "string", "object", "category"}:
            continue

        unique_count = _safe_int(
            column_profile.get("unique_count"),
            fallback=0,
        )
        unique_ratio = (
            round(unique_count / dataset_row_count, 4)
            if dataset_row_count > 0
            else 0.0
        )

        is_high_cardinality = (
            unique_count >= config.high_cardinality_unique_threshold
            and unique_ratio >= config.high_cardinality_ratio_threshold
        )

        if not is_high_cardinality:
            continue

        _add_warning(
            warnings,
            warning_type="high_cardinality_column",
            severity="warning",
            message=(
                f"The source dataset column '{column}' has high cardinality."
            ),
            column=column,
            recommendation=(
                "Avoid using this column directly as a chart category unless "
                "the result is grouped, filtered, or limited."
            ),
            metadata={
                "unique_count": unique_count,
                "dataset_row_count": dataset_row_count,
                "unique_ratio": unique_ratio,
            },
        )
        _add_recommendation(
            recommendations,
            recommendation_type="group_or_limit_high_cardinality_column",
            priority="medium",
            message=(
                f"Use grouping, filtering, or a top-N query before charting "
                f"'{column}'."
            ),
            column=column,
        )


def _add_duplicate_warnings(
    *,
    warnings: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    results: list[dict[str, Any]],
    schema_profile: dict[str, Any],
) -> None:
    duplicate_row_count = _extract_duplicate_row_count(schema_profile)

    if duplicate_row_count is not None and duplicate_row_count > 0:
        _add_warning(
            warnings,
            warning_type="duplicate_rows_detected",
            severity="warning",
            message=(
                "The trusted dataset metadata indicates duplicate rows may exist."
            ),
            recommendation=(
                "Do not remove duplicates automatically. Recommend a cleaning step "
                "only if the user approves it later."
            ),
            metadata={
                "duplicate_row_count": duplicate_row_count,
                "source": "schema_profile",
            },
        )
        _add_recommendation(
            recommendations,
            recommendation_type="consider_duplicate_review",
            priority="medium",
            message=(
                "Consider reviewing duplicate rows with a future Data Cleaning Agent "
                "before making final conclusions."
            ),
        )

    duplicate_result_rows = _count_duplicate_result_rows(results)

    if duplicate_result_rows > 0:
        _add_warning(
            warnings,
            warning_type="duplicate_result_rows_detected",
            severity="info",
            message=(
                "The query result contains repeated rows."
            ),
            recommendation=(
                "Use DISTINCT or grouping only if repeated rows are not expected."
            ),
            metadata={
                "duplicate_result_rows": duplicate_result_rows,
                "source": "query_result",
            },
        )


def _add_warning(
    warnings: list[dict[str, Any]],
    *,
    warning_type: str,
    severity: str,
    message: str,
    column: str | None = None,
    recommendation: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    warnings.append(
        {
            "warning_type": warning_type,
            "severity": severity,
            "message": message,
            "column": column,
            "recommendation": recommendation,
            "metadata": metadata or {},
        }
    )


def _add_recommendation(
    recommendations: list[dict[str, Any]],
    *,
    recommendation_type: str,
    priority: str,
    message: str,
    column: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    recommendations.append(
        {
            "recommendation_type": recommendation_type,
            "priority": priority,
            "message": message,
            "column": column,
            "metadata": metadata or {},
        }
    )


def _get_result_columns(results: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []

    for row in results:
        for column in row.keys():
            if column not in columns:
                columns.append(column)

    return columns


def _has_inconsistent_result_shape(
    results: list[dict[str, Any]],
) -> bool:
    if not results:
        return False

    expected_columns = set(results[0].keys())

    return any(
        set(row.keys()) != expected_columns
        for row in results
    )


def _profile_columns_by_name(
    schema_profile: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    columns = schema_profile.get("columns")

    if not isinstance(columns, list):
        return {}

    return {
        column["name"]: column
        for column in columns
        if isinstance(column, dict)
        and isinstance(column.get("name"), str)
    }


def _extract_duplicate_row_count(
    schema_profile: dict[str, Any],
) -> int | None:
    dataset_profile = schema_profile.get("dataset", {})

    candidate_keys = [
        "duplicate_row_count",
        "duplicate_count",
        "duplicate_rows",
    ]

    for key in candidate_keys:
        if key in dataset_profile:
            return _safe_int(dataset_profile.get(key), fallback=0)

        if key in schema_profile:
            return _safe_int(schema_profile.get(key), fallback=0)

    return None


def _count_duplicate_result_rows(
    results: list[dict[str, Any]],
) -> int:
    seen: set[str] = set()
    duplicate_count = 0

    for row in results:
        row_key = json.dumps(
            row,
            sort_keys=True,
            default=str,
        )

        if row_key in seen:
            duplicate_count += 1
        else:
            seen.add(row_key)

    return duplicate_count


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback