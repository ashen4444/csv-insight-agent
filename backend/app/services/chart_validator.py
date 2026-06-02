from typing import Any


def validate_chart_selection(
    analysis: dict[str, Any],
    chart_selection: dict[str, Any],
    chart_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if chart_selection.get("chart_generation_enabled") is not True:
        return _no_warning()

    final_chart_type = chart_selection.get("final_chart_type")
    recommended_chart_type = analysis.get("recommended_visualization")

    if chart_payload is None:
        return _warning(
            warning_type="chart_payload_unavailable",
            message="Chart generation was requested, but the system could not build a chart payload from the query result.",
        )

    if final_chart_type != recommended_chart_type:
        return _warning(
            warning_type="chart_type_mismatch",
            message=(
                f"A {final_chart_type} was requested, but the result appears more suitable "
                f"for {recommended_chart_type}."
            ),
        )

    return _no_warning()


def _warning(warning_type: str, message: str) -> dict[str, Any]:
    return {
        "has_warning": True,
        "warning_type": warning_type,
        "message": message,
    }


def _no_warning() -> dict[str, Any]:
    return {
        "has_warning": False,
        "warning_type": None,
        "message": None,
    }