# backend/tests/agents/test_chart_agent.py

import pytest
from pydantic import ValidationError

from app.agents.chart_agent import (
    ChartAgent,
    ChartAgentErrorType,
    ChartAgentInput,
    ChartGenerationStatus,
)


def _base_input(**overrides):
    payload = {
        "dataset_id": "dataset_123",
        "question": "Generate a bar chart of average salary by country",
        "sql": 'SELECT "Country", AVG("Salary") AS "avg_salary" FROM table GROUP BY "Country"',
        "results": [
            {"Country": "UK", "avg_salary": 100000},
            {"Country": "USA", "avg_salary": 120000},
        ],
        "row_count": 2,
        "success": True,
        "execution_success": True,
        "executed": True,
        "execution_status": "execution_succeeded",
        "execution_time_ms": 12.5,
        "data_quality_status": "quality_passed",
        "is_result_usable": True,
        "is_result_empty": False,
        "is_result_too_large": False,
        "has_visualization_warnings": False,
        "request_id": "req_123",
        "metadata": {"source": "unit_test"},
    }
    payload.update(overrides)
    return ChartAgentInput(**payload)


def test_generates_chart_for_explicit_bar_chart_request():
    agent = ChartAgent()

    output = agent.generate(_base_input())

    assert output.success is True
    assert output.chart_generation_status == ChartGenerationStatus.GENERATED
    assert output.chart_generation_enabled is True
    assert output.is_chart_available is True
    assert output.chart_type == "bar"
    assert output.selected_chart_type == "bar_chart"
    assert output.requested_chart_type == "bar_chart"
    assert output.recommended_chart_type == "bar_chart"
    assert output.chart_payload is not None
    assert output.chart_payload["x_axis"] == "Country"
    assert output.chart_payload["y_axis"] == "avg_salary"
    assert output.chart_payload["data"] == output.model_dump()["chart_payload"]["data"]
    assert output.error_type is None


def test_does_not_generate_chart_when_not_requested_but_recommendation_exists():
    agent = ChartAgent()

    output = agent.generate(
        _base_input(question="Average salary by country")
    )

    assert output.success is True
    assert output.chart_generation_status == ChartGenerationStatus.NOT_REQUESTED
    assert output.chart_generation_enabled is False
    assert output.is_chart_available is False
    assert output.is_chart_recommended is True
    assert output.recommended_chart_type == "bar_chart"
    assert output.chart_payload is None
    assert output.error_type is None


def test_generates_chart_when_generation_is_approved_after_recommendation():
    agent = ChartAgent()

    output = agent.generate(
        _base_input(
            question="Average salary by country",
            chart_generation_approved=True,
        )
    )

    assert output.success is True
    assert output.chart_generation_status == ChartGenerationStatus.GENERATED
    assert output.chart_generation_enabled is True
    assert output.is_chart_available is True
    assert output.chart_type == "bar"
    assert output.chart_source == "analyzer_recommendation"
    assert output.visualization_intent["approval_source"] == (
        "chart_generation_approved"
    )


def test_blocks_chart_when_upstream_execution_failed():
    agent = ChartAgent()

    output = agent.generate(
        _base_input(
            success=False,
            execution_success=False,
            executed=False,
            execution_status="execution_failed",
            error_type="execution_error",
            error_message="DuckDB execution failed.",
        )
    )

    assert output.success is False
    assert output.chart_generation_status == ChartGenerationStatus.BLOCKED
    assert output.error_type == (
        ChartAgentErrorType.UPSTREAM_EXECUTION_NOT_SUCCESSFUL
    )
    assert output.is_chart_available is False
    assert output.chart_payload is None
    assert output.chart_warning is not None
    assert output.chart_warning.severity == "critical"


def test_blocks_chart_when_data_quality_marks_result_unusable():
    agent = ChartAgent()

    output = agent.generate(
        _base_input(
            data_quality_status="quality_warning",
            is_result_usable=False,
        )
    )

    assert output.success is False
    assert output.chart_generation_status == ChartGenerationStatus.BLOCKED
    assert output.error_type == ChartAgentErrorType.DATA_QUALITY_BLOCKED
    assert output.is_chart_available is False
    assert output.chart_payload is None
    assert output.chart_warning is not None


def test_blocks_chart_for_empty_result():
    agent = ChartAgent()

    output = agent.generate(
        _base_input(
            results=[],
            row_count=0,
            is_result_empty=True,
        )
    )

    assert output.success is False
    assert output.chart_generation_status == ChartGenerationStatus.BLOCKED
    assert output.error_type == ChartAgentErrorType.DATA_QUALITY_BLOCKED
    assert output.chart_payload is None


def test_blocks_chart_for_too_large_result():
    agent = ChartAgent()

    output = agent.generate(
        _base_input(
            is_result_too_large=True,
        )
    )

    assert output.success is False
    assert output.chart_generation_status == ChartGenerationStatus.BLOCKED
    assert output.error_type == ChartAgentErrorType.DATA_QUALITY_BLOCKED
    assert output.chart_payload is None


def test_returns_unavailable_for_metric_card_payload_not_supported_yet():
    agent = ChartAgent()

    output = agent.generate(
        _base_input(
            question="Show this as a metric card",
            results=[{"avg_salary": 100000}],
            row_count=1,
        )
    )

    assert output.success is False
    assert output.chart_generation_status == ChartGenerationStatus.UNAVAILABLE
    assert output.error_type == ChartAgentErrorType.CHART_PAYLOAD_UNAVAILABLE
    assert output.selected_chart_type == "metric_card"
    assert output.recommended_chart_type == "metric_card"
    assert output.chart_payload is None
    assert output.chart_warning is not None


def test_generates_chart_with_warning_when_requested_type_differs_from_recommendation():
    agent = ChartAgent()

    output = agent.generate(
        _base_input(
            question="Generate a line chart of average salary by country",
        )
    )

    assert output.success is True
    assert output.chart_generation_status == (
        ChartGenerationStatus.GENERATED_WITH_WARNING
    )
    assert output.chart_type == "line"
    assert output.selected_chart_type == "line_chart"
    assert output.recommended_chart_type == "bar_chart"
    assert output.chart_warning is not None
    assert output.chart_warning.warning_type == "chart_type_mismatch"


def test_blocks_unknown_visualization_warning_without_details():
    agent = ChartAgent()

    output = agent.generate(
        _base_input(
            has_visualization_warnings=True,
            quality_warnings=[],
        )
    )

    assert output.success is False
    assert output.chart_generation_status == ChartGenerationStatus.BLOCKED
    assert output.error_type == ChartAgentErrorType.DATA_QUALITY_BLOCKED


def test_allows_non_critical_visualization_warning_but_returns_chart_warning():
    agent = ChartAgent()

    output = agent.generate(
        _base_input(
            has_visualization_warnings=True,
            quality_warnings=[
                {
                    "warning_type": "high_cardinality_visualization",
                    "severity": "warning",
                    "message": "Chart may be crowded.",
                }
            ],
        )
    )

    assert output.success is True
    assert output.chart_generation_status == (
        ChartGenerationStatus.GENERATED_WITH_WARNING
    )
    assert output.chart_payload is not None
    assert output.chart_warning is not None
    assert output.chart_warning.source == "data_quality_agent"


def test_blocks_critical_visualization_warning():
    agent = ChartAgent()

    output = agent.generate(
        _base_input(
            has_visualization_warnings=True,
            quality_warnings=[
                {
                    "warning_type": "misleading_visualization",
                    "severity": "critical",
                    "message": "Chart would be misleading.",
                }
            ],
        )
    )

    assert output.success is False
    assert output.chart_generation_status == ChartGenerationStatus.BLOCKED
    assert output.error_type == ChartAgentErrorType.DATA_QUALITY_BLOCKED
    assert output.chart_payload is None


def test_returns_failed_when_visualization_intent_service_response_is_invalid():
    agent = ChartAgent(
        visualization_intent_detector=lambda question: {
            "requested_chart_type": "bar_chart"
        }
    )

    output = agent.generate(_base_input())

    assert output.success is False
    assert output.chart_generation_status == ChartGenerationStatus.FAILED
    assert output.error_type == ChartAgentErrorType.INVALID_SERVICE_RESPONSE
    assert output.chart_payload is None


def test_returns_failed_when_result_analyzer_response_is_invalid():
    agent = ChartAgent(
        result_analyzer=lambda *args, **kwargs: {
            "result_type": "categorical_numeric"
        }
    )

    output = agent.generate(_base_input())

    assert output.success is False
    assert output.chart_generation_status == ChartGenerationStatus.FAILED
    assert output.error_type == ChartAgentErrorType.INVALID_SERVICE_RESPONSE
    assert output.chart_payload is None


def test_returns_failed_when_chart_selector_response_is_invalid():
    agent = ChartAgent(
        chart_selector=lambda analysis, intent: {
            "chart_generation_enabled": True
        }
    )

    output = agent.generate(_base_input())

    assert output.success is False
    assert output.chart_generation_status == ChartGenerationStatus.FAILED
    assert output.error_type == ChartAgentErrorType.INVALID_SERVICE_RESPONSE
    assert output.chart_payload is None


def test_returns_failed_when_chart_validator_response_is_invalid():
    agent = ChartAgent(
        chart_validator=lambda analysis, selection, payload: {
            "has_warning": False
        }
    )

    output = agent.generate(_base_input())

    assert output.success is False
    assert output.chart_generation_status == ChartGenerationStatus.FAILED
    assert output.error_type == ChartAgentErrorType.INVALID_SERVICE_RESPONSE
    assert output.chart_payload is None


def test_invalid_result_payload_row_count_mismatch_is_blocked():
    agent = ChartAgent()

    output = agent.generate(
        _base_input(row_count=3)
    )

    assert output.success is False
    assert output.chart_generation_status == ChartGenerationStatus.BLOCKED
    assert output.error_type == ChartAgentErrorType.INVALID_RESULT_PAYLOAD
    assert output.chart_payload is None


def test_to_dict_serializes_enums():
    agent = ChartAgent()

    output = agent.generate(_base_input())
    serialized = output.to_dict()

    assert serialized["chart_generation_status"] == "chart_generated"
    assert serialized["chart_type"] == "bar"
    assert serialized["error_type"] is None
    assert serialized["metadata"]["agent"] == "ChartAgent"


def test_input_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ChartAgentInput(
            **{
                **_base_input().model_dump(),
                "schema_context": {"unsafe": "caller provided"},
            }
        )