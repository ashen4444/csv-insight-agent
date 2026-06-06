# backend/tests/agents/test_query_executor_agent.py

import pytest
from pydantic import ValidationError

from app.agents.query_executor_agent import (
    QueryExecutionStatus,
    QueryExecutorAgent,
    QueryExecutorAgentInput,
    QueryExecutorErrorType,
)


def test_executes_safe_validated_sql_using_query_executor_service() -> None:
    def fake_query_executor(sql):
        assert sql == 'SELECT "Country" FROM "test_table";'

        return {
            "sql": 'SELECT "Country" FROM "test_table" LIMIT 100',
            "row_count": 2,
            "execution_time_ms": 4.25,
            "results": [
                {"Country": "Sri Lanka"},
                {"Country": "India"},
            ],
        }

    agent = QueryExecutorAgent(query_executor=fake_query_executor)

    result = agent.execute(
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            is_safe_to_execute=True,
            validation_status="valid",
            request_id="req_123",
            metadata={"source": "unit_test"},
        )
    )

    assert result.success is True
    assert result.executed is True
    assert result.execution_status == QueryExecutionStatus.SUCCEEDED
    assert result.sql == 'SELECT "Country" FROM "test_table" LIMIT 100'
    assert result.row_count == 2
    assert result.execution_time_ms == 4.25
    assert result.results == [
        {"Country": "Sri Lanka"},
        {"Country": "India"},
    ]
    assert result.error_type is None
    assert result.error_message is None
    assert result.blocking_reason is None
    assert result.metadata["agent"] == "QueryExecutorAgent"
    assert result.metadata["service"] == "execute_query"
    assert result.metadata["request_id"] == "req_123"
    assert result.metadata["source"] == "unit_test"
    assert result.metadata["validation_status"] == "valid"
    assert result.metadata["is_safe_to_execute"] is True
    assert result.metadata["guardrail_passed"] is True
    assert result.metadata["execution_attempted"] is True
    assert result.metadata["safe_limit_may_have_been_applied"] is True


def test_rejects_caller_provided_schema_context_table_name_or_schema_profile() -> None:
    with pytest.raises(ValidationError):
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            is_safe_to_execute=True,
            validation_status="valid",
            schema_context={"table_name": "fake_table"},
        )

    with pytest.raises(ValidationError):
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            is_safe_to_execute=True,
            validation_status="valid",
            table_name="fake_table",
        )

    with pytest.raises(ValidationError):
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            is_safe_to_execute=True,
            validation_status="valid",
            schema_profile={"columns": ["fake_column"]},
        )


def test_rejects_caller_provided_allowed_columns() -> None:
    with pytest.raises(ValidationError):
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            is_safe_to_execute=True,
            validation_status="valid",
            allowed_columns=["fake_column"],
        )


def test_blocks_empty_sql_before_calling_query_executor() -> None:
    def fake_query_executor(sql):
        raise AssertionError("Query executor should not be called.")

    agent = QueryExecutorAgent(query_executor=fake_query_executor)

    result = agent.execute(
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql="",
            is_safe_to_execute=True,
            validation_status="valid",
        )
    )

    assert result.success is False
    assert result.executed is False
    assert result.execution_status == QueryExecutionStatus.BLOCKED
    assert result.error_type == QueryExecutorErrorType.EMPTY_SQL
    assert result.blocking_reason == "SQL is empty."
    assert result.metadata["execution_attempted"] is False
    assert result.metadata["guardrail_passed"] is False


def test_blocks_whitespace_sql_before_calling_query_executor() -> None:
    def fake_query_executor(sql):
        raise AssertionError("Query executor should not be called.")

    agent = QueryExecutorAgent(query_executor=fake_query_executor)

    result = agent.execute(
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql="   ",
            is_safe_to_execute=True,
            validation_status="valid",
        )
    )

    assert result.success is False
    assert result.executed is False
    assert result.execution_status == QueryExecutionStatus.BLOCKED
    assert result.error_type == QueryExecutorErrorType.EMPTY_SQL


def test_blocks_sql_when_not_marked_safe_to_execute() -> None:
    def fake_query_executor(sql):
        raise AssertionError("Query executor should not be called.")

    agent = QueryExecutorAgent(query_executor=fake_query_executor)

    result = agent.execute(
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Delete the table",
            sql='DROP TABLE "test_table";',
            is_safe_to_execute=False,
            validation_status="blocked",
        )
    )

    assert result.success is False
    assert result.executed is False
    assert result.execution_status == QueryExecutionStatus.BLOCKED
    assert result.error_type == QueryExecutorErrorType.UNSAFE_SQL
    assert result.blocking_reason == (
        "SQL was not marked safe to execute by the SQL Validator / Guardrail Agent."
    )
    assert result.metadata["execution_attempted"] is False
    assert result.metadata["guardrail_passed"] is False


def test_blocks_sql_when_validation_status_is_not_valid() -> None:
    def fake_query_executor(sql):
        raise AssertionError("Query executor should not be called.")

    agent = QueryExecutorAgent(query_executor=fake_query_executor)

    result = agent.execute(
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            is_safe_to_execute=True,
            validation_status="error",
        )
    )

    assert result.success is False
    assert result.executed is False
    assert result.execution_status == QueryExecutionStatus.BLOCKED
    assert result.error_type == QueryExecutorErrorType.VALIDATION_NOT_PASSED
    assert result.blocking_reason == "SQL validation status is 'error', not 'valid'."
    assert result.metadata["execution_attempted"] is False
    assert result.metadata["guardrail_passed"] is False


def test_executes_when_validation_status_is_omitted_but_sql_is_safe() -> None:
    def fake_query_executor(sql):
        return {
            "sql": sql,
            "row_count": 1,
            "execution_time_ms": 2.0,
            "results": [{"Country": "Sri Lanka"}],
        }

    agent = QueryExecutorAgent(query_executor=fake_query_executor)

    result = agent.execute(
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table" LIMIT 1;',
            is_safe_to_execute=True,
        )
    )

    assert result.success is True
    assert result.executed is True
    assert result.execution_status == QueryExecutionStatus.SUCCEEDED
    assert result.metadata["validation_status"] is None


def test_returns_failure_when_query_executor_service_is_unavailable() -> None:
    class BrokenQueryExecutorAgent(QueryExecutorAgent):
        def _resolve_query_executor(self):
            raise ImportError("query executor dependency missing")

    agent = BrokenQueryExecutorAgent()

    result = agent.execute(
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            is_safe_to_execute=True,
            validation_status="valid",
        )
    )

    assert result.success is False
    assert result.executed is False
    assert result.execution_status == QueryExecutionStatus.FAILED
    assert result.error_type == QueryExecutorErrorType.QUERY_EXECUTOR_UNAVAILABLE
    assert "query executor dependency missing" in result.error_message
    assert result.metadata["exception_type"] == "ImportError"
    assert result.metadata["execution_attempted"] is False


def test_returns_failure_when_query_executor_raises_value_error() -> None:
    def failing_query_executor(sql):
        raise ValueError("Query execution failed or exceeded timeout limit.")

    agent = QueryExecutorAgent(query_executor=failing_query_executor)

    result = agent.execute(
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            is_safe_to_execute=True,
            validation_status="valid",
        )
    )

    assert result.success is False
    assert result.executed is False
    assert result.execution_status == QueryExecutionStatus.FAILED
    assert result.error_type == QueryExecutorErrorType.QUERY_EXECUTION_FAILED
    assert "Query execution failed" in result.error_message
    assert result.metadata["exception_type"] == "ValueError"
    assert result.metadata["execution_attempted"] is True
    assert result.metadata["guardrail_passed"] is True


def test_returns_failure_when_query_executor_raises_unexpected_exception() -> None:
    def failing_query_executor(sql):
        raise RuntimeError("Unexpected DuckDB connection failure")

    agent = QueryExecutorAgent(query_executor=failing_query_executor)

    result = agent.execute(
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            is_safe_to_execute=True,
            validation_status="valid",
        )
    )

    assert result.success is False
    assert result.executed is False
    assert result.execution_status == QueryExecutionStatus.FAILED
    assert result.error_type == QueryExecutorErrorType.UNEXPECTED_EXECUTION_ERROR
    assert "Unexpected DuckDB connection failure" in result.error_message
    assert result.metadata["exception_type"] == "RuntimeError"


def test_returns_failure_when_query_executor_response_is_invalid() -> None:
    def invalid_query_executor(sql):
        return {
            "sql": sql,
            "row_count": 1,
            "execution_time_ms": 1.5,
        }

    agent = QueryExecutorAgent(query_executor=invalid_query_executor)

    result = agent.execute(
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            is_safe_to_execute=True,
            validation_status="valid",
        )
    )

    assert result.success is False
    assert result.executed is False
    assert result.execution_status == QueryExecutionStatus.FAILED
    assert result.error_type == QueryExecutorErrorType.INVALID_EXECUTOR_RESPONSE
    assert "missing key" in result.error_message
    assert result.metadata["execution_attempted"] is True


def test_result_can_be_serialized_to_dict() -> None:
    def fake_query_executor(sql):
        return {
            "sql": sql,
            "row_count": 1,
            "execution_time_ms": 3.75,
            "results": [{"Country": "Sri Lanka"}],
        }

    agent = QueryExecutorAgent(query_executor=fake_query_executor)

    result = agent.execute(
        QueryExecutorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table" LIMIT 1;',
            is_safe_to_execute=True,
            validation_status="valid",
        )
    )

    payload = result.to_dict()

    assert payload["success"] is True
    assert payload["executed"] is True
    assert payload["execution_status"] == "execution_succeeded"
    assert payload["row_count"] == 1
    assert payload["execution_time_ms"] == 3.75
    assert payload["results"] == [{"Country": "Sri Lanka"}]
    assert payload["error_type"] is None
    assert "metadata" in payload