# backend/tests/agents/test_answer_formatter_agent.py

from pydantic import ValidationError

from app.agents.answer_formatter_agent import (
    AnswerFormatterAgent,
    AnswerFormatterAgentInput,
    AnswerFormatterErrorType,
    AnswerResponseStatus,
    AnswerResponseType,
)


def _base_input(**overrides):
    data = {
        "dataset_id": "dataset_123",
        "question": "Average salary by country",
        "primary_intent": "analytics_query",
        "required_capabilities": [
            "sql_generation",
            "sql_validation",
            "query_execution",
            "result_analysis",
            "answer_formatting",
        ],
        "routing_confidence": 0.95,
        "routing_reason": "Analytical question detected.",
        "routing_source": "rule_based",
        "is_routable": True,
        "sql": 'SELECT "Country", AVG("Salary") AS "avg_salary" FROM table GROUP BY "Country"',
        "sql_generation_success": True,
        "validation_success": True,
        "validation_status": "valid",
        "is_valid": True,
        "is_safe_to_execute": True,
        "execution_success": True,
        "execution_status": "execution_succeeded",
        "executed": True,
        "results": [
            {"Country": "Sri Lanka", "avg_salary": 1000.0},
            {"Country": "India", "avg_salary": 1200.0},
        ],
        "row_count": 2,
        "execution_time_ms": 12.5,
        "data_quality_success": True,
        "quality_status": "quality_passed",
        "is_result_usable": True,
        "is_result_empty": False,
        "is_result_too_large": False,
        "has_null_warnings": False,
        "has_duplicate_warnings": False,
        "has_visualization_warnings": False,
        "chart_success": True,
        "chart_generation_status": "chart_not_requested",
        "chart_generation_enabled": False,
        "is_chart_available": False,
        "is_chart_recommended": False,
    }

    data.update(overrides)

    return AnswerFormatterAgentInput(**data)


def test_formats_successful_table_answer():
    formatter = AnswerFormatterAgent()

    output = formatter.format(_base_input())

    assert output.success is True
    assert output.response_status == AnswerResponseStatus.READY
    assert output.response_type == AnswerResponseType.TEXT_WITH_TABLE
    assert output.display_result_count == 2
    assert output.display_columns == ["Country", "avg_salary"]
    assert output.chart_available is False
    assert output.chart_payload is None
    assert output.error_type is None


def test_formats_answer_ready_with_data_quality_warning():
    formatter = AnswerFormatterAgent()

    output = formatter.format(
        _base_input(
            quality_status="quality_warning",
            has_null_warnings=True,
            quality_warnings=[
                {
                    "warning_type": "null_values_detected",
                    "severity": "warning",
                    "message": "Some result columns contain null values.",
                    "column": "avg_salary",
                    "recommendation": "Review null values before making decisions.",
                    "metadata": {"null_count": 3},
                }
            ],
            quality_recommendations=[
                {
                    "recommendation_type": "review_nulls",
                    "priority": "medium",
                    "message": "Consider reviewing null values.",
                    "column": "avg_salary",
                    "metadata": {"column": "avg_salary"},
                }
            ],
        )
    )

    assert output.success is True
    assert output.response_status == AnswerResponseStatus.READY_WITH_WARNING
    assert len(output.warnings) == 1
    assert output.warnings[0].source == "data_quality_agent"
    assert len(output.recommendations) == 1
    assert "warnings" in output.message.lower()


def test_formats_no_results_response():
    formatter = AnswerFormatterAgent()

    output = formatter.format(
        _base_input(
            results=[],
            row_count=0,
            is_result_empty=True,
        )
    )

    assert output.success is True
    assert output.response_status == AnswerResponseStatus.NO_RESULTS
    assert output.response_type == AnswerResponseType.TEXT_ANSWER
    assert output.display_results == []
    assert output.chart_available is False
    assert "did not return any rows" in output.message


def test_formats_unsupported_query():
    formatter = AnswerFormatterAgent()

    output = formatter.format(
        _base_input(
            primary_intent="unsupported_query",
            required_capabilities=[
                "unsupported_response",
                "answer_formatting",
            ],
            unsupported_reason="non_csv_task",
            sql=None,
            sql_generation_success=None,
            validation_success=None,
            execution_success=None,
            executed=None,
            results=[],
            row_count=None,
            data_quality_success=None,
        )
    )

    assert output.success is False
    assert output.response_status == AnswerResponseStatus.UNSUPPORTED
    assert output.response_type == AnswerResponseType.UNSUPPORTED_MESSAGE
    assert output.error_type == AnswerFormatterErrorType.UNSUPPORTED_QUERY
    assert output.chart_available is False
    assert "CSV" in output.message


def test_formats_clarification_response():
    formatter = AnswerFormatterAgent()

    output = formatter.format(
        _base_input(
            needs_clarification=True,
            clarification_question="Which column do you want to analyze?",
            sql=None,
            sql_generation_success=None,
            validation_success=None,
            execution_success=None,
            executed=None,
            results=[],
            row_count=None,
            data_quality_success=None,
        )
    )

    assert output.success is False
    assert output.response_status == AnswerResponseStatus.NEEDS_CLARIFICATION
    assert output.response_type == AnswerResponseType.CLARIFICATION_MESSAGE
    assert output.error_type == AnswerFormatterErrorType.NEEDS_CLARIFICATION
    assert output.message == "Which column do you want to analyze?"


def test_formats_validation_blocked_response():
    formatter = AnswerFormatterAgent()

    output = formatter.format(
        _base_input(
            validation_success=False,
            validation_status="blocked",
            is_valid=False,
            is_safe_to_execute=False,
            validation_error_type="sql_validation_failed",
            validation_error_message="Subqueries are not supported yet.",
            validation_blocking_reason="Subqueries are not supported yet.",
            execution_success=None,
            executed=None,
            execution_status=None,
            results=[],
            row_count=None,
            data_quality_success=None,
        )
    )

    assert output.success is False
    assert output.response_status == AnswerResponseStatus.BLOCKED
    assert output.response_type == AnswerResponseType.ERROR_MESSAGE
    assert output.error_type == AnswerFormatterErrorType.SQL_VALIDATION_BLOCKED
    assert "did not pass validation" in output.message


def test_formats_execution_failed_response():
    formatter = AnswerFormatterAgent()

    output = formatter.format(
        _base_input(
            execution_success=False,
            execution_status="execution_failed",
            executed=False,
            execution_error_type="query_execution_failed",
            execution_error_message="DuckDB execution failed.",
            execution_blocking_reason="Query execution failed in the execution service.",
            results=[],
            row_count=0,
            data_quality_success=None,
        )
    )

    assert output.success is False
    assert output.response_status == AnswerResponseStatus.FAILED
    assert output.response_type == AnswerResponseType.ERROR_MESSAGE
    assert output.error_type == AnswerFormatterErrorType.EXECUTION_FAILED
    assert "could not be executed" in output.message


def test_formats_data_quality_blocked_response():
    formatter = AnswerFormatterAgent()

    output = formatter.format(
        _base_input(
            data_quality_success=True,
            quality_status="quality_failed",
            is_result_usable=False,
            quality_error_type="invalid_result_payload",
            quality_error_message="Result payload is invalid.",
            quality_blocking_reason="Result is not usable.",
        )
    )

    assert output.success is False
    assert output.response_status == AnswerResponseStatus.BLOCKED
    assert output.response_type == AnswerResponseType.ERROR_MESSAGE
    assert output.error_type == AnswerFormatterErrorType.DATA_QUALITY_BLOCKED
    assert "data quality checks did not pass" in output.message


def test_includes_generated_chart_payload():
    formatter = AnswerFormatterAgent()

    chart_payload = {
        "chart_type": "bar_chart",
        "x_axis": "Country",
        "y_axis": "avg_salary",
        "data": [
            {"x": "Sri Lanka", "y": 1000.0},
            {"x": "India", "y": 1200.0},
        ],
    }

    output = formatter.format(
        _base_input(
            primary_intent="visualization_query",
            chart_success=True,
            chart_generation_status="chart_generated",
            chart_generation_enabled=True,
            chart_type="bar_chart",
            selected_chart_type="bar_chart",
            requested_chart_type="bar_chart",
            recommended_chart_type="bar_chart",
            chart_payload=chart_payload,
            is_chart_available=True,
            is_chart_recommended=True,
        )
    )

    assert output.success is True
    assert output.response_status == AnswerResponseStatus.READY
    assert output.response_type == AnswerResponseType.TEXT_WITH_TABLE_AND_CHART
    assert output.chart_available is True
    assert output.chart_type == "bar_chart"
    assert output.chart_payload == chart_payload
    assert "chart" in output.message.lower()


def test_chart_unavailable_does_not_pretend_chart_exists():
    formatter = AnswerFormatterAgent()

    output = formatter.format(
        _base_input(
            primary_intent="visualization_query",
            chart_success=False,
            chart_generation_status="chart_unavailable",
            chart_generation_enabled=True,
            chart_type=None,
            selected_chart_type="metric_card",
            requested_chart_type="metric_card",
            recommended_chart_type="metric_card",
            chart_payload=None,
            is_chart_available=False,
            is_chart_recommended=True,
            chart_error_type="chart_payload_unavailable",
            chart_error_message="The selected chart type is unsupported.",
            chart_blocking_reason="metric_card payload is not supported yet.",
        )
    )

    assert output.success is True
    assert output.response_status == AnswerResponseStatus.READY_WITH_WARNING
    assert output.chart_available is False
    assert output.chart_payload is None
    assert len(output.warnings) == 1
    assert output.warnings[0].source == "chart_agent"
    assert "could not be generated" in output.message


def test_chart_not_requested_adds_recommendation_when_chart_is_recommended():
    formatter = AnswerFormatterAgent()

    output = formatter.format(
        _base_input(
            chart_generation_status="chart_not_requested",
            is_chart_available=False,
            is_chart_recommended=True,
            recommended_chart_type="bar_chart",
        )
    )

    assert output.success is True
    assert output.chart_available is False
    assert len(output.recommendations) == 1
    assert output.recommendations[0].recommendation_type == "chart_recommended"


def test_to_dict_serializes_enums_as_strings():
    formatter = AnswerFormatterAgent()

    output = formatter.format(_base_input())
    serialized = output.to_dict()

    assert serialized["response_status"] == "answer_ready"
    assert serialized["response_type"] == "text_with_table"
    assert serialized["chart_available"] is False


def test_input_rejects_trusted_schema_context_from_caller():
    try:
        AnswerFormatterAgentInput(
            dataset_id="dataset_123",
            question="Average salary by country",
            schema_context={"table_name": "unsafe"},
        )
    except ValidationError as exc:
        assert "schema_context" in str(exc)
    else:
        raise AssertionError("schema_context should not be accepted.")