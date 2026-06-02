from typing import Any


CHART_TYPE_MAP = {
    "bar_chart": "bar",
    "line_chart": "line",
    "scatter_plot": "scatter",
}


def build_chart_payload(
    results: list[dict[str, Any]],
    analysis: dict[str, Any],
    chart_selection: dict[str, Any],
) -> dict[str, Any] | None:
    if chart_selection.get("chart_generation_enabled") is not True:
        return None

    final_chart_type = chart_selection.get("final_chart_type")

    if final_chart_type not in CHART_TYPE_MAP:
        return None

    x_axis = analysis.get("x_axis")
    y_axis = analysis.get("y_axis")

    if not x_axis or not y_axis:
        return None

    return {
        "chart_type": CHART_TYPE_MAP[final_chart_type],
        "x_axis": x_axis,
        "y_axis": y_axis,
        "data": results,
    }