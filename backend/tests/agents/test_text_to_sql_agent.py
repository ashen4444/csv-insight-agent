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


def test_generates_sql_with_provided_schema_context() -> None:
    def fake_sql_generator(table_name, schema_profile, question):
        assert table_name == "test_table"
        assert schema_profile["columns"][0]["name"] == "Country"
        assert question == "Average salary by country"

        return (
            'SELECT "Country", AVG("Average_Salary_USD") AS avg_salary '
            'FROM "test_table" GROUP BY "Country";'
        )

    agent = TextToSQLAgent(sql_generator=fake_sql_generator)

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
            schema_context=build_schema_context(),
        )
    )

    assert result.success is True
    assert result.sql is not None
    assert "SELECT" in result.sql
    assert result.error_type is None
    assert result.schema_context_source == SchemaContextSource.PROVIDED
    assert result.model_available is True
    assert result.metadata["agent"] == "TextToSQLAgent"
    assert result.metadata["service"] == "generate_sql_from_question"


def test_builds_schema_context_when_not_provided() -> None:
    def fake_schema_context_builder(dataset_id):
        assert dataset_id == "8d2b0bcd63ad"
        return build_schema_context()

    def fake_sql_generator(table_name, schema_profile, question):
        return 'SELECT DISTINCT "Country" FROM "test_table";'

    agent = TextToSQLAgent(
        sql_generator=fake_sql_generator,
        schema_context_builder=fake_schema_context_builder,
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show countries",
        )
    )

    assert result.success is True
    assert result.sql == 'SELECT DISTINCT "Country" FROM "test_table";'
    assert result.schema_context_source == SchemaContextSource.BUILT_FROM_DATASET_ID


def test_blocks_when_model_unavailable() -> None:
    def fake_sql_generator(table_name, schema_profile, question):
        raise AssertionError("SQL generator should not be called.")

    agent = TextToSQLAgent(sql_generator=fake_sql_generator)

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
            model_available=False,
            schema_context=build_schema_context(),
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.MODEL_UNAVAILABLE
    assert result.model_available is False


def test_returns_error_when_schema_context_missing() -> None:
    def fake_schema_context_builder(dataset_id):
        return None

    agent = TextToSQLAgent(schema_context_builder=fake_schema_context_builder)

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
        sql_generator=lambda table_name, schema_profile, question: "SELECT 1;"
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
            schema_context=schema_context,
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.INVALID_SCHEMA_CONTEXT


def test_returns_error_when_schema_profile_is_invalid() -> None:
    schema_context = build_schema_context()
    schema_context["schema_profile"] = None

    agent = TextToSQLAgent(
        sql_generator=lambda table_name, schema_profile, question: "SELECT 1;"
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
            schema_context=schema_context,
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.INVALID_SCHEMA_CONTEXT


def test_returns_error_when_schema_columns_missing() -> None:
    schema_context = build_schema_context()
    schema_context["schema_profile"].pop("columns")

    agent = TextToSQLAgent(
        sql_generator=lambda table_name, schema_profile, question: "SELECT 1;"
    )

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
            schema_context=schema_context,
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.INVALID_SCHEMA_CONTEXT


def test_returns_error_when_sql_generator_returns_empty_string() -> None:
    def fake_sql_generator(table_name, schema_profile, question):
        return "   "

    agent = TextToSQLAgent(sql_generator=fake_sql_generator)

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
            schema_context=build_schema_context(),
        )
    )

    assert result.success is False
    assert result.sql is None
    assert result.error_type == TextToSQLErrorType.EMPTY_SQL_GENERATED


def test_returns_error_when_sql_generator_fails() -> None:
    def failing_sql_generator(table_name, schema_profile, question):
        raise RuntimeError("LLM request failed")

    agent = TextToSQLAgent(sql_generator=failing_sql_generator)

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Average salary by country",
            schema_context=build_schema_context(),
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

    agent = TextToSQLAgent(sql_generator=fake_sql_generator)

    result = agent.generate(
        TextToSQLAgentInput(
            dataset_id="8d2b0bcd63ad",
            question="Show first 5 rows",
            schema_context=build_schema_context(),
        )
    )

    payload = result.to_dict()

    assert payload["success"] is True
    assert payload["sql"] == 'SELECT * FROM "test_table" LIMIT 5;'
    assert payload["schema_context_source"] == "provided"
    assert "metadata" in payload