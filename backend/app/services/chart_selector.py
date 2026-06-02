from typing import Any


def select_chart(
    analysis: dict[str, Any],
    visualization_intent: dict[str, Any],
) -> dict[str, Any]:
    visualization_requested = visualization_intent.get("visualization_requested", False)
    requested_chart_type = visualization_intent.get("requested_chart_type")

    if not visualization_requested:
        return {
            "chart_generation_enabled": False,
            "final_chart_type": None,
            "chart_source": None,
        }

    if requested_chart_type is not None:
        return {
            "chart_generation_enabled": True,
            "final_chart_type": requested_chart_type,
            "chart_source": "user_request",
        }

    if analysis.get("is_visualizable") is True:
        return {
            "chart_generation_enabled": True,
            "final_chart_type": analysis.get("recommended_visualization"),
            "chart_source": "analyzer_recommendation",
        }

    return {
        "chart_generation_enabled": False,
        "final_chart_type": None,
        "chart_source": None,
    }