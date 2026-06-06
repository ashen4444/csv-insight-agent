# backend/tests/agents/test_data_quality_agent.py

import pytest
from pydantic import ValidationError

from app.agents.data_quality_agent import (
    DataQualityAgent,
    DataQualityAgentInput,
    DataQualityErrorType,
    DataQualityStatus,
)


DATASET_ID = "8d2b0bcd63ad"


def _schema_context(
    columns=None,
    row_count=100,
    duplicate_row_count=None,
):
    if columns is None:
        columns = [
            {
                "name": "Country",
                "pandas_dtype": "object",
                "inferred_type": "text",
                "null_count": 0,
                "non_null_count": row_count,
                "null_percentage": 0.0,
                "unique_count": 5,
                "numeric_stats": None,
                "sample_values": ["Sri Lanka", "India"],
            },
            {
                "name": "avg_salary",
                "pandas_dtype": "float64",
                "inferred_type": "float",
                "null_count": 0,
                "non_null_count": row_count,
                "null_percentage": 0.0,
                "unique_count": 20,
                "numeric_stats": {
                    "min": 100.0,
                    "max": 200.0,
                    "mean": 150.0,
                    "median": 150.0,
                    "std": 10.0,
                },
                "sample_values": None,
            },
        ]

    dataset_profile = {
        "original_filename": "test.csv",
        "table_name": "test_table",
        "row_count": row_count,
        "column_count": len(columns),
    }

    if duplicate_row_count is not None:
        dataset_profile["duplicate_row_count"] = duplicate_row_count

    return {
        "dataset_id": DATASET_ID,
        "table_name": "test_table",
        "row_count": row_count,
        "column_count": len(columns),
        "schema_profile": {
            "dataset": dataset_profile,
            "columns": columns,
            "privacy_note": (
                "Raw CSV rows are not included. This profile only contains "
                "schema metadata and safe summary statistics."
            ),
        },
    }


def test_evaluates_successful_execution_and_returns_quality_passed() -> None:
    def fake_schema_context_builder(dataset_id):
        assert dataset_id == DATASET_ID
        return _schema_context()

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.evaluate(
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Average salary by country",
            sql='SELECT "Country", AVG("Salary") AS avg_salary FROM test_table GROUP BY "Country";',
            success=True,
            executed=True,
            execution_status="execution_succeeded",
            results=[
                {"Country": "Sri Lanka", "avg_salary": 100.0},
                {"Country": "India", "avg_salary": 120.0},
            ],
            row_count=2,
            execution_time_ms=4.25,
            request_id="req_123",
            metadata={"source": "unit_test"},
        )
    )

    assert result.success is True
    assert result.quality_status == DataQualityStatus.PASSED
    assert result.is_result_usable is True
    assert result.is_result_empty is False
    assert result.is_result_too_large is False
    assert result.has_null_warnings is False
    assert result.has_duplicate_warnings is False
    assert result.has_visualization_warnings is False
    assert result.row_count == 2
    assert result.execution_time_ms == 4.25
    assert result.warnings == []
    assert result.recommendations == []
    assert result.error_type is None
    assert result.metadata["agent"] == "DataQualityAgent"
    assert result.metadata["service"] == "evaluate_data_quality"
    assert result.metadata["schema_context_source"] == "build_schema_context"
    assert result.metadata["request_id"] == "req_123"
    assert result.metadata["source"] == "unit_test"
    assert result.metadata["quality_evaluated"] is True
    assert result.metadata["schema_context_resolved"] is True


def test_accepts_query_executor_output_dict_shape() -> None:
    def fake_schema_context_builder(dataset_id):
        return _schema_context()

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    query_executor_output = {
        "success": True,
        "dataset_id": DATASET_ID,
        "question": "Show countries",
        "sql": 'SELECT "Country" FROM "test_table" LIMIT 2',
        "executed": True,
        "execution_status": "execution_succeeded",
        "results": [
            {"Country": "Sri Lanka"},
            {"Country": "India"},
        ],
        "row_count": 2,
        "execution_time_ms": 2.5,
        "error_type": None,
        "error_message": None,
        "blocking_reason": None,
        "metadata": {"from_agent": "QueryExecutorAgent"},
    }

    result = agent.evaluate(
        DataQualityAgentInput(**query_executor_output)
    )

    assert result.success is True
    assert result.quality_status in {
        DataQualityStatus.PASSED,
        DataQualityStatus.WARNING,
    }
    assert result.metadata["from_agent"] == "QueryExecutorAgent"


def test_rejects_caller_provided_schema_context_table_name_or_schema_profile() -> None:
    with pytest.raises(ValidationError):
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Show countries",
            results=[],
            row_count=0,
            schema_context={"table_name": "fake_table"},
        )

    with pytest.raises(ValidationError):
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Show countries",
            results=[],
            row_count=0,
            table_name="fake_table",
        )

    with pytest.raises(ValidationError):
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Show countries",
            results=[],
            row_count=0,
            schema_profile={"columns": []},
        )


def test_rejects_caller_provided_allowed_columns() -> None:
    with pytest.raises(ValidationError):
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Show countries",
            results=[],
            row_count=0,
            allowed_columns=["fake_column"],
        )


def test_returns_quality_not_evaluated_when_upstream_execution_failed() -> None:
    def fake_schema_context_builder(dataset_id):
        raise AssertionError("Schema context should not be resolved.")

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.evaluate(
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            success=False,
            executed=False,
            execution_status="execution_failed",
            results=[],
            row_count=0,
            error_type="query_execution_failed",
            error_message="DuckDB execution failed.",
            blocking_reason="Query execution failed in the execution service.",
        )
    )

    assert result.success is False
    assert result.quality_status == DataQualityStatus.NOT_EVALUATED
    assert result.error_type == DataQualityErrorType.EXECUTION_NOT_SUCCESSFUL
    assert result.is_result_usable is False
    assert result.metadata["quality_evaluated"] is False
    assert result.metadata["schema_context_resolved"] is False
    assert result.warnings[0].warning_type == "execution_not_successful"


def test_returns_failed_when_schema_context_not_found() -> None:
    def fake_schema_context_builder(dataset_id):
        return None

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.evaluate(
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Show countries",
            success=True,
            executed=True,
            execution_status="execution_succeeded",
            results=[{"Country": "Sri Lanka"}],
            row_count=1,
        )
    )

    assert result.success is False
    assert result.quality_status == DataQualityStatus.FAILED
    assert result.error_type == DataQualityErrorType.SCHEMA_CONTEXT_NOT_FOUND
    assert result.is_result_usable is False
    assert result.warnings[0].warning_type == "dataset_metadata_unavailable"


def test_returns_failed_when_schema_context_is_invalid() -> None:
    def fake_schema_context_builder(dataset_id):
        return {
            "dataset_id": DATASET_ID,
            "table_name": "test_table",
            "row_count": 10,
            "column_count": 1,
            "schema_profile": {
                "columns": "invalid_columns_payload",
            },
        }

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.evaluate(
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Show countries",
            success=True,
            executed=True,
            execution_status="execution_succeeded",
            results=[{"Country": "Sri Lanka"}],
            row_count=1,
        )
    )

    assert result.success is False
    assert result.quality_status == DataQualityStatus.FAILED
    assert result.error_type == DataQualityErrorType.INVALID_SCHEMA_CONTEXT
    assert "schema_profile.columns must be a list" in result.error_message


def test_returns_invalid_result_payload_when_row_count_does_not_match_results() -> None:
    def fake_schema_context_builder(dataset_id):
        raise AssertionError("Schema context should not be resolved.")

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.evaluate(
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Show countries",
            success=True,
            executed=True,
            execution_status="execution_succeeded",
            results=[{"Country": "Sri Lanka"}],
            row_count=2,
        )
    )

    assert result.success is False
    assert result.quality_status == DataQualityStatus.FAILED
    assert result.error_type == DataQualityErrorType.INVALID_RESULT_PAYLOAD
    assert "row_count does not match" in result.error_message
    assert result.warnings[0].warning_type == "invalid_result_payload"


def test_empty_result_returns_quality_failed_but_evaluation_successful() -> None:
    def fake_schema_context_builder(dataset_id):
        return _schema_context()

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.evaluate(
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Show countries where country equals Atlantis",
            success=True,
            executed=True,
            execution_status="execution_succeeded",
            results=[],
            row_count=0,
        )
    )

    assert result.success is True
    assert result.quality_status == DataQualityStatus.FAILED
    assert result.is_result_usable is False
    assert result.is_result_empty is True
    assert result.error_type is None
    assert result.warnings[0].warning_type == "empty_result"
    assert result.recommendations[0].recommendation_type == "adjust_query_filters"


def test_adds_null_heavy_dataset_warning_for_relevant_column() -> None:
    columns = [
        {
            "name": "Country",
            "pandas_dtype": "object",
            "inferred_type": "text",
            "null_count": 50,
            "non_null_count": 50,
            "null_percentage": 50.0,
            "unique_count": 5,
            "numeric_stats": None,
            "sample_values": ["Sri Lanka", "India"],
        },
    ]

    def fake_schema_context_builder(dataset_id):
        return _schema_context(columns=columns, row_count=100)

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.evaluate(
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Show countries",
            success=True,
            executed=True,
            execution_status="execution_succeeded",
            results=[
                {"Country": "Sri Lanka"},
                {"Country": "India"},
            ],
            row_count=2,
        )
    )

    warning_types = {
        warning.warning_type
        for warning in result.warnings
    }

    assert result.success is True
    assert result.quality_status == DataQualityStatus.WARNING
    assert result.has_null_warnings is True
    assert "null_heavy_column" in warning_types


def test_adds_result_null_warning() -> None:
    def fake_schema_context_builder(dataset_id):
        return _schema_context()

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.evaluate(
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Average salary by country",
            success=True,
            executed=True,
            execution_status="execution_succeeded",
            results=[
                {"Country": "Sri Lanka", "avg_salary": 100.0},
                {"Country": "India", "avg_salary": None},
            ],
            row_count=2,
        )
    )

    warning_types = {
        warning.warning_type
        for warning in result.warnings
    }

    assert result.success is True
    assert result.quality_status == DataQualityStatus.WARNING
    assert result.has_null_warnings is True
    assert "result_null_values_detected" in warning_types


def test_adds_visualization_warning_for_large_chart_result() -> None:
    columns = [
        {
            "name": "Country",
            "pandas_dtype": "object",
            "inferred_type": "text",
            "null_count": 0,
            "non_null_count": 100,
            "null_percentage": 0.0,
            "unique_count": 5,
            "numeric_stats": None,
            "sample_values": ["Sri Lanka", "India"],
        },
        {
            "name": "avg_salary",
            "pandas_dtype": "float64",
            "inferred_type": "float",
            "null_count": 0,
            "non_null_count": 100,
            "null_percentage": 0.0,
            "unique_count": 50,
            "numeric_stats": None,
            "sample_values": None,
        },
    ]

    def fake_schema_context_builder(dataset_id):
        return _schema_context(columns=columns, row_count=100)

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    results = [
        {
            "Country": f"Country {index}",
            "avg_salary": float(index),
        }
        for index in range(31)
    ]

    result = agent.evaluate(
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Show average salary by country",
            success=True,
            executed=True,
            execution_status="execution_succeeded",
            results=results,
            row_count=31,
        )
    )

    warning_types = {
        warning.warning_type
        for warning in result.warnings
    }

    assert result.success is True
    assert result.quality_status == DataQualityStatus.WARNING
    assert result.has_visualization_warnings is True
    assert "visualization_not_recommended" in warning_types


def test_adds_high_cardinality_warning_for_profile_column() -> None:
    columns = [
        {
            "name": "employee_id",
            "pandas_dtype": "object",
            "inferred_type": "text",
            "null_count": 0,
            "non_null_count": 100,
            "null_percentage": 0.0,
            "unique_count": 95,
            "numeric_stats": None,
            "sample_values": ["E001", "E002"],
        },
    ]

    def fake_schema_context_builder(dataset_id):
        return _schema_context(columns=columns, row_count=100)

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.evaluate(
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Show employee ids",
            success=True,
            executed=True,
            execution_status="execution_succeeded",
            results=[
                {"employee_id": "E001"},
                {"employee_id": "E002"},
            ],
            row_count=2,
        )
    )

    warning_types = {
        warning.warning_type
        for warning in result.warnings
    }

    assert result.success is True
    assert result.quality_status == DataQualityStatus.WARNING
    assert "high_cardinality_column" in warning_types


def test_adds_duplicate_warning_when_profile_has_duplicate_metadata() -> None:
    def fake_schema_context_builder(dataset_id):
        return _schema_context(
            row_count=100,
            duplicate_row_count=10,
        )

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.evaluate(
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Average salary by country",
            success=True,
            executed=True,
            execution_status="execution_succeeded",
            results=[
                {"Country": "Sri Lanka", "avg_salary": 100.0},
                {"Country": "India", "avg_salary": 120.0},
            ],
            row_count=2,
        )
    )

    warning_types = {
        warning.warning_type
        for warning in result.warnings
    }

    assert result.success is True
    assert result.quality_status == DataQualityStatus.WARNING
    assert result.has_duplicate_warnings is True
    assert "duplicate_rows_detected" in warning_types


def test_result_can_be_serialized_to_dict() -> None:
    def fake_schema_context_builder(dataset_id):
        return _schema_context()

    agent = DataQualityAgent(
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.evaluate(
        DataQualityAgentInput(
            dataset_id=DATASET_ID,
            question="Average salary by country",
            success=True,
            executed=True,
            execution_status="execution_succeeded",
            results=[
                {"Country": "Sri Lanka", "avg_salary": 100.0},
                {"Country": "India", "avg_salary": 120.0},
            ],
            row_count=2,
            execution_time_ms=3.75,
        )
    )

    payload = result.to_dict()

    assert payload["success"] is True
    assert payload["quality_status"] == "quality_passed"
    assert payload["is_result_usable"] is True
    assert payload["row_count"] == 2
    assert payload["execution_time_ms"] == 3.75
    assert payload["error_type"] is None
    assert "metadata" in payload