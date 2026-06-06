import pytest
from pydantic import ValidationError

from app.agents.text_to_sql_agent import (
    SchemaContextSource,
    TextToSQLAgent,
    TextToSQLAgentInput,
    TextToSQLErrorType,
)


def build_schema_context() -> dict:
    return {
        "dataset_id": "8d2b0bcd63ad",
        "table_name": "test_table",
        "row_count": 100,
        "column_count": 2,
        "schema_profile": {
            "dataset": {
                "original_filename": "test.csv",
                "table_name": "test_table",
                "row_count": 100,
                "column_count": 2,
            },
            "columns": [
                {
                    "name": "Country",
                    "pandas_dtype": "object",
                    "inferred_type": "text",
                    "null_count": 0,
                    "non_null_count": 100,
                    "null_percentage": 0,
                    "unique_count": 5,
                    "numeric_stats": None,
                    "sample_values": ["Sri Lanka", "India"],
                },
                {
                    "name": "Average_Salary_USD",
                    "pandas_dtype": "float64",
                    "inferred_type": "float",
                    "null_count": 0,
                    "non_null_count": 100,
                    "null_percentage": 0,
                    "unique_count": 100,
                    "numeric_stats": {
                        "min": 1000.0,
                        "max": 5000.0,
                        "mean": 3000.0,
                        "median": 3000.0,
                        "std": 500.0,
                    },
                    "sample_values": None,
                },
            ],
            "privacy_note": "Raw CSV rows are not included.",
        },
    }


def test_input_rejects_caller_provided_schema_context() -> None:
    with pytest.raises(ValidationError):
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
            schema_context=build_schema_context(),
        )


def test_input_rejects_caller_provided_schema_profile() -> None:
    with pytest.raises(ValidationError):
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
            schema_profile={"columns": []},
        )


def test_generates_sql_after_resolving_schema_context_from_dataset_id() -> None:
    def fake_schema_context_builder(dataset_id):
        assert dataset_id == "8d2b0bcd63ad"
        return build_schema_context()

    def fake_sql_generator(table_name, schema_profile, question):
        assert table_name == "test_table"
        assert schema_profile["columns"][0]["name"] == "Country"
        assert question == "Average salary by country"

        return (
            'SELECT "Country", AVG("Average_Salary_USD") AS avg_salary '
            'FROM "test_table" GROUP BY "Country";'
        )

    agent = TextToSQLAgent(
        sql_generator=fake_sql_generator,
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
        )
    )

    assert result.success is True
    assert result.sql is not None
    assert "SELECT" in result.sql
    assert result.error_type is None
    assert result.schema_context_source == SchemaContextSource.RESOLVED_FROM_DATASET_ID
    assert result.metadata["agent"] == "TextToSQLAgent"
    assert result.metadata["service"] == "generate_sql_from_question"
    assert result.metadata["raw_rows_sent_to_llm"] is False


def test_does_not_call_sql_generator_when_schema_context_missing() -> None:
    def fake_schema_context_builder(dataset_id):
        return None

    def fake_sql_generator(table_name, schema_profile, question):
        raise AssertionError("SQL generator should not be called without schema context.")

    agent = TextToSQLAgent(
        sql_generator=fake_sql_generator,
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="missing_dataset",
            question="Average salary by country",
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.SCHEMA_CONTEXT_NOT_FOUND


def test_returns_error_when_table_name_missing() -> None:
    schema_context = build_schema_context()
    schema_context.pop("table_name")

    agent = TextToSQLAgent(
        sql_generator=lambda table_name, schema_profile, question: "SELECT 1;",
        schema_context_builder=lambda dataset_id: schema_context,
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.INVALID_SCHEMA_CONTEXT


def test_returns_error_when_schema_profile_is_invalid() -> None:
    schema_context = build_schema_context()
    schema_context["schema_profile"] = None

    agent = TextToSQLAgent(
        sql_generator=lambda table_name, schema_profile, question: "SELECT 1;",
        schema_context_builder=lambda dataset_id: schema_context,
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.INVALID_SCHEMA_CONTEXT


def test_returns_error_when_schema_columns_missing() -> None:
    schema_context = build_schema_context()
    schema_context["schema_profile"].pop("columns")

    agent = TextToSQLAgent(
        sql_generator=lambda table_name, schema_profile, question: "SELECT 1;",
        schema_context_builder=lambda dataset_id: schema_context,
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.INVALID_SCHEMA_CONTEXT


def test_returns_error_when_schema_context_contains_raw_row_payload() -> None:
    schema_context = build_schema_context()
    schema_context["rows"] = [
        {"Country": "Sri Lanka", "Average_Salary_USD": 3000}
    ]

    agent = TextToSQLAgent(
        sql_generator=lambda table_name, schema_profile, question: "SELECT 1;",
        schema_context_builder=lambda dataset_id: schema_context,
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.INVALID_SCHEMA_CONTEXT
    assert "raw row payload" in result.error_message


def test_returns_error_when_schema_profile_contains_raw_row_payload() -> None:
    schema_context = build_schema_context()
    schema_context["schema_profile"]["records"] = [
        {"Country": "Sri Lanka", "Average_Salary_USD": 3000}
    ]

    agent = TextToSQLAgent(
        sql_generator=lambda table_name, schema_profile, question: "SELECT 1;",
        schema_context_builder=lambda dataset_id: schema_context,
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.INVALID_SCHEMA_CONTEXT
    assert "raw row payload" in result.error_message


def test_returns_error_when_sql_generator_returns_empty_string() -> None:
    def fake_sql_generator(table_name, schema_profile, question):
        return "   "

    agent = TextToSQLAgent(
        sql_generator=fake_sql_generator,
        schema_context_builder=lambda dataset_id: build_schema_context(),
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.EMPTY_SQL_GENERATED


def test_returns_error_when_sql_generator_fails() -> None:
    def failing_sql_generator(table_name, schema_profile, question):
        raise RuntimeError("LLM request failed")

    agent = TextToSQLAgent(
        sql_generator=failing_sql_generator,
        schema_context_builder=lambda dataset_id: build_schema_context(),
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.SQL_GENERATION_FAILED
    assert "LLM request failed" in result.error_message
    assert result.metadata["exception_type"] == "RuntimeError"


def test_result_can_be_serialized_to_dict() -> None:
    def fake_sql_generator(table_name, schema_profile, question):
        return 'SELECT * FROM "test_table" LIMIT 5;'

    agent = TextToSQLAgent(
        sql_generator=fake_sql_generator,
        schema_context_builder=lambda dataset_id: build_schema_context(),
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show first 5 rows",
            request_id="req_123",
            metadata={"source": "unit_test"},
        )
    )

    payload = result.to_dict()

    assert payload["success"] is True
    assert payload["sql"] == 'SELECT * FROM "test_table" LIMIT 5;'
    assert payload["schema_context_source"] == "resolved_from_dataset_id"
    assert payload["metadata"]["request_id"] == "req_123"
    assert payload["metadata"]["source"] == "unit_test"
    assert "metadata" in payload