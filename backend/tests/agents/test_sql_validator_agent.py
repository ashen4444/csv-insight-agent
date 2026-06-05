from app.agents.sql_validator_agent import (
    SQLValidationErrorType,
    SQLValidationStatus,
    SQLValidatorAgent,
    SQLValidatorAgentInput,
    SQLValidatorSchemaContextSource,
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


def test_validates_safe_sql_with_provided_schema_context() -> None:
    def fake_sql_validator(sql, schema_context):
        assert sql == 'SELECT "Country" FROM "test_table";'
        assert schema_context["table_name"] == "test_table"

    agent = SQLValidatorAgent(sql_validator=fake_sql_validator)

    result = agent.validate(
        SQLValidatorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            schema_context=build_schema_context(),
        )
    )

    assert result.success is True
    assert result.validation_status == SQLValidationStatus.VALID
    assert result.is_valid is True
    assert result.is_safe_to_execute is True
    assert result.error_type is None
    assert result.blocking_reason is None
    assert result.schema_context_source == SQLValidatorSchemaContextSource.PROVIDED
    assert result.metadata["agent"] == "SQLValidatorAgent"
    assert result.metadata["service"] == "validate_sql"
    assert result.metadata["guardrail_passed"] is True


def test_builds_schema_context_when_not_provided() -> None:
    def fake_schema_context_builder(dataset_id):
        assert dataset_id == "8d2b0bcd63ad"
        return build_schema_context()

    def fake_sql_validator(sql, schema_context):
        assert sql == 'SELECT DISTINCT "Country" FROM "test_table";'
        assert schema_context["table_name"] == "test_table"

    agent = SQLValidatorAgent(
        sql_validator=fake_sql_validator,
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.validate(
        SQLValidatorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show unique countries",
            sql='SELECT DISTINCT "Country" FROM "test_table";',
        )
    )

    assert result.success is True
    assert result.validation_status == SQLValidationStatus.VALID
    assert result.schema_context_source == (
        SQLValidatorSchemaContextSource.BUILT_FROM_DATASET_ID
    )


def test_blocks_empty_sql_before_calling_validator() -> None:
    def fake_sql_validator(sql, schema_context):
        raise AssertionError("SQL validator should not be called.")

    agent = SQLValidatorAgent(sql_validator=fake_sql_validator)

    result = agent.validate(
        SQLValidatorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql="",
            schema_context=build_schema_context(),
        )
    )

    assert result.success is False
    assert result.validation_status == SQLValidationStatus.BLOCKED
    assert result.is_valid is False
    assert result.is_safe_to_execute is False
    assert result.error_type == SQLValidationErrorType.EMPTY_SQL
    assert result.blocking_reason == "Generated SQL is empty."


def test_blocks_whitespace_sql_before_calling_validator() -> None:
    def fake_sql_validator(sql, schema_context):
        raise AssertionError("SQL validator should not be called.")

    agent = SQLValidatorAgent(sql_validator=fake_sql_validator)

    result = agent.validate(
        SQLValidatorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql="   ",
            schema_context=build_schema_context(),
        )
    )

    assert result.success is False
    assert result.validation_status == SQLValidationStatus.BLOCKED
    assert result.is_valid is False
    assert result.is_safe_to_execute is False
    assert result.error_type == SQLValidationErrorType.EMPTY_SQL
    assert result.blocking_reason == "Generated SQL is empty."


def test_returns_error_when_schema_context_missing() -> None:
    def fake_schema_context_builder(dataset_id):
        return None

    def fake_sql_validator(sql, schema_context):
        raise AssertionError("SQL validator should not be called.")

    agent = SQLValidatorAgent(
        sql_validator=fake_sql_validator,
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.validate(
        SQLValidatorAgentInput(
            dataset_id="missing_dataset",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
        )
    )

    assert result.success is False
    assert result.validation_status == SQLValidationStatus.ERROR
    assert result.is_safe_to_execute is False
    assert result.error_type == SQLValidationErrorType.SCHEMA_CONTEXT_NOT_FOUND
    assert result.blocking_reason == "SQL cannot be validated without schema context."


def test_returns_error_when_table_name_missing() -> None:
    schema_context = build_schema_context()
    schema_context.pop("table_name")

    def fake_sql_validator(sql, schema_context):
        raise AssertionError("SQL validator should not be called.")

    agent = SQLValidatorAgent(sql_validator=fake_sql_validator)

    result = agent.validate(
        SQLValidatorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            schema_context=schema_context,
        )
    )

    assert result.success is False
    assert result.validation_status == SQLValidationStatus.ERROR
    assert result.error_type == SQLValidationErrorType.INVALID_SCHEMA_CONTEXT
    assert result.blocking_reason == (
        "SQL cannot be validated because schema context is invalid."
    )


def test_returns_error_when_schema_profile_is_invalid() -> None:
    schema_context = build_schema_context()
    schema_context["schema_profile"] = None

    def fake_sql_validator(sql, schema_context):
        raise AssertionError("SQL validator should not be called.")

    agent = SQLValidatorAgent(sql_validator=fake_sql_validator)

    result = agent.validate(
        SQLValidatorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            schema_context=schema_context,
        )
    )

    assert result.success is False
    assert result.validation_status == SQLValidationStatus.ERROR
    assert result.error_type == SQLValidationErrorType.INVALID_SCHEMA_CONTEXT


def test_returns_error_when_schema_columns_metadata_is_invalid() -> None:
    schema_context = build_schema_context()
    schema_context["schema_profile"]["columns"] = None

    def fake_sql_validator(sql, schema_context):
        raise AssertionError("SQL validator should not be called.")

    agent = SQLValidatorAgent(sql_validator=fake_sql_validator)

    result = agent.validate(
        SQLValidatorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            schema_context=schema_context,
        )
    )

    assert result.success is False
    assert result.validation_status == SQLValidationStatus.ERROR
    assert result.error_type == SQLValidationErrorType.INVALID_SCHEMA_CONTEXT


def test_blocks_sql_when_validator_raises_value_error() -> None:
    def fake_sql_validator(sql, schema_context):
        raise ValueError("Forbidden SQL keyword detected: DROP")

    agent = SQLValidatorAgent(sql_validator=fake_sql_validator)

    result = agent.validate(
        SQLValidatorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Delete the table",
            sql='DROP TABLE "test_table";',
            schema_context=build_schema_context(),
        )
    )

    assert result.success is False
    assert result.validation_status == SQLValidationStatus.BLOCKED
    assert result.is_valid is False
    assert result.is_safe_to_execute is False
    assert result.error_type == SQLValidationErrorType.SQL_VALIDATION_FAILED
    assert result.blocking_reason == "Forbidden SQL keyword detected: DROP"
    assert result.metadata["guardrail_passed"] is False
    assert result.metadata["exception_type"] == "ValueError"


def test_returns_error_when_validator_service_is_unavailable() -> None:
    class BrokenSQLValidatorAgent(SQLValidatorAgent):
        def _resolve_sql_validator(self):
            raise ImportError("sql validator dependency missing")

    agent = BrokenSQLValidatorAgent()

    result = agent.validate(
        SQLValidatorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            schema_context=build_schema_context(),
        )
    )

    assert result.success is False
    assert result.validation_status == SQLValidationStatus.ERROR
    assert result.error_type == SQLValidationErrorType.SQL_VALIDATOR_UNAVAILABLE
    assert "sql validator dependency missing" in result.error_message
    assert result.is_safe_to_execute is False


def test_returns_error_when_validator_raises_unexpected_exception() -> None:
    def failing_sql_validator(sql, schema_context):
        raise RuntimeError("Unexpected parser failure")

    agent = SQLValidatorAgent(sql_validator=failing_sql_validator)

    result = agent.validate(
        SQLValidatorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
            sql='SELECT "Country" FROM "test_table";',
            schema_context=build_schema_context(),
        )
    )

    assert result.success is False
    assert result.validation_status == SQLValidationStatus.ERROR
    assert result.error_type == SQLValidationErrorType.UNEXPECTED_VALIDATION_ERROR
    assert "Unexpected parser failure" in result.error_message
    assert result.metadata["exception_type"] == "RuntimeError"


def test_result_can_be_serialized_to_dict() -> None:
    def fake_sql_validator(sql, schema_context):
        return None

    agent = SQLValidatorAgent(sql_validator=fake_sql_validator)

    result = agent.validate(
        SQLValidatorAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show first 5 rows",
            sql='SELECT * FROM "test_table" LIMIT 5;',
            schema_context=build_schema_context(),
        )
    )

    payload = result.to_dict()

    assert payload["success"] is True
    assert payload["validation_status"] == "valid"
    assert payload["is_valid"] is True
    assert payload["is_safe_to_execute"] is True
    assert payload["schema_context_source"] == "provided"
    assert payload["sql"] == 'SELECT * FROM "test_table" LIMIT 5;'
    assert "metadata" in payload