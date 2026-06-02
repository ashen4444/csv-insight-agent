import re
from typing import Any


CHART_TYPE_ALIASES = {
    "bar_chart": [
        "bar chart",
        "bar graph",
        "column chart",
        "column graph",
    ],
    "line_chart": [
        "line chart",
        "line graph",
        "trend chart",
        "trend graph",
    ],
    "scatter_plot": [
        "scatter plot",
        "scatter chart",
        "scatter graph",
    ],
    "metric_card": [
        "metric card",
        "kpi card",
        "summary card",
    ],
    "table": [
        "table",
        "tabular",
        "rows",
    ],
}


GENERIC_VISUALIZATION_KEYWORDS = [
    "visualize",
    "visualise",
    "show chart",
    "show graph",
    "plot",
    "draw chart",
    "draw graph",
    "generate chart",
    "create chart",
    "make chart",
]


def detect_visualization_intent(question: str) -> dict[str, Any]:
    normalized_question = question.lower().strip()

    requested_chart_type = _detect_requested_chart_type(normalized_question)

    if requested_chart_type is not None:
        return {
            "visualization_requested": True,
            "requested_chart_type": requested_chart_type,
        }

    visualization_requested = _has_generic_visualization_intent(normalized_question)

    return {
        "visualization_requested": visualization_requested,
        "requested_chart_type": None,
    }


def _detect_requested_chart_type(question: str) -> str | None:
    for chart_type, aliases in CHART_TYPE_ALIASES.items():
        for alias in aliases:
            pattern = rf"\b{re.escape(alias)}\b"
            if re.search(pattern, question):
                return chart_type

    return None


def _has_generic_visualization_intent(question: str) -> bool:
    for keyword in GENERIC_VISUALIZATION_KEYWORDS:
        pattern = rf"\b{re.escape(keyword)}\b"
        if re.search(pattern, question):
            return True

    return False