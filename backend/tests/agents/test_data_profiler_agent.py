from __future__ import annotations

import inspect
from typing import Any

import app.agents.data_profiler_agent as data_profiler_agent_module
from app.agents.data_profiler_agent import (
    DataProfilerAgent,
    DataProfilerAgentInput,
)


DATASET_ID = "8d2b0bcd63ad"
REQUEST_ID = "request-123"


def sample_schema_profile() -> dict[str, Any]:
    return {
        "dataset": {
            "row_count": 100,
            "column_count": 2,
        },
        "columns": [
            {
                "name": "Country",
                "inferred_type": "categorical",
                "null_count": 0,
                "unique_count": 5,
            },
            {
                "name": "Average_Salary_USD",
                "inferred_type": "numeric",
                "null_count": 0,
                "unique_count": 25,
                "min": 45000,
                "max": 150000,
                "mean": 85000,
            },
        ]
    }


def sample_dataset(schema_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "dataset_id": DATASET_ID,
        "table_name": "ai_impact_on_jobs_2030_47d7dd3144f7",
        "row_count": 100,
        "column_count": 2,
        "schema_profile": (
            sample_schema_profile()
            if schema_profile is None
            else schema_profile
        ),
    }


def sample_schema_context() -> dict[str, Any]:
    return {
        "dataset_id": DATASET_ID,
        "table_name": "ai_impact_on_jobs_2030_47d7dd3144f7",
        "row_count": 100,
        "column_count": 2,
        "schema_profile": sample_schema_profile(),
    }


def test_returns_successful_profile_and_schema_context_for_valid_dataset_id() -> None:
    lookup_calls: list[str] = []
    context_builder_calls: list[str] = []

    def dataset_lookup_fn(dataset_id: str) -> dict[str, Any] | None:
        lookup_calls.append(dataset_id)
        return sample_dataset()

    def schema_context_builder_fn(dataset_id: str) -> dict[str, Any] | None:
        context_builder_calls.append(dataset_id)
        return sample_schema_context()

    agent = DataProfilerAgent(
        dataset_lookup_fn=dataset_lookup_fn,
        schema_context_builder_fn=schema_context_builder_fn,
    )

    result = agent.run(
        DataProfilerAgentInput(
            dataset_id=DATASET_ID,
            request_id=REQUEST_ID,
            metadata={"source": "unit_test"},
        )
    )

    assert result.success is True
    assert result.dataset_id == DATASET_ID
    assert result.table_name == "ai_impact_on_jobs_2030_47d7dd3144f7"
    assert result.row_count == 100
    assert result.column_count == 2
    assert result.schema_profile == sample_schema_profile()
    assert result.schema_context == sample_schema_context()
    assert result.profiling_status == "completed"
    assert result.error_type is None
    assert result.request_id == REQUEST_ID
    assert result.metadata == {"source": "unit_test"}

    assert lookup_calls == [DATASET_ID]
    assert context_builder_calls == [DATASET_ID]


def test_returns_dataset_not_found_when_registry_has_no_dataset() -> None:
    def dataset_lookup_fn(dataset_id: str) -> dict[str, Any] | None:
        return None

    def schema_context_builder_fn(dataset_id: str) -> dict[str, Any] | None:
        raise AssertionError("Schema context should not be built for missing datasets.")

    agent = DataProfilerAgent(
        dataset_lookup_fn=dataset_lookup_fn,
        schema_context_builder_fn=schema_context_builder_fn,
    )

    result = agent.run(DataProfilerAgentInput(dataset_id=DATASET_ID))

    assert result.success is False
    assert result.dataset_id == DATASET_ID
    assert result.schema_profile is None
    assert result.schema_context is None
    assert result.profiling_status == "dataset_not_found"
    assert result.error_type == "DATASET_NOT_FOUND"
    assert result.message == "Dataset was not found in the dataset registry."


def test_returns_missing_schema_profile_when_dataset_has_no_stored_profile() -> None:
    def dataset_lookup_fn(dataset_id: str) -> dict[str, Any] | None:
        dataset = sample_dataset()
        dataset["schema_profile"] = None
        return dataset

    def schema_context_builder_fn(dataset_id: str) -> dict[str, Any] | None:
        raise AssertionError(
            "Schema context should not be built when schema_profile is missing."
        )

    agent = DataProfilerAgent(
        dataset_lookup_fn=dataset_lookup_fn,
        schema_context_builder_fn=schema_context_builder_fn,
    )

    result = agent.run(DataProfilerAgentInput(dataset_id=DATASET_ID))

    assert result.success is False
    assert result.dataset_id == DATASET_ID
    assert result.schema_profile is None
    assert result.schema_context is None
    assert result.profiling_status == "missing_schema_profile"
    assert result.error_type == "MISSING_SCHEMA_PROFILE"
    assert result.message == "Dataset exists, but no schema profile is stored for it."


def test_returns_schema_context_build_failure_when_builder_returns_none() -> None:
    def dataset_lookup_fn(dataset_id: str) -> dict[str, Any] | None:
        return sample_dataset()

    def schema_context_builder_fn(dataset_id: str) -> dict[str, Any] | None:
        return None

    agent = DataProfilerAgent(
        dataset_lookup_fn=dataset_lookup_fn,
        schema_context_builder_fn=schema_context_builder_fn,
    )

    result = agent.run(DataProfilerAgentInput(dataset_id=DATASET_ID))

    assert result.success is False
    assert result.dataset_id == DATASET_ID
    assert result.schema_profile is None
    assert result.schema_context is None
    assert result.profiling_status == "schema_context_build_failed"
    assert result.error_type == "SCHEMA_CONTEXT_BUILD_FAILED"
    assert result.message == (
        "Schema context builder returned no context for the dataset."
    )


def test_returns_schema_context_build_failure_when_context_is_incomplete() -> None:
    def dataset_lookup_fn(dataset_id: str) -> dict[str, Any] | None:
        return sample_dataset()

    def schema_context_builder_fn(dataset_id: str) -> dict[str, Any] | None:
        return {
            "dataset_id": DATASET_ID,
            "table_name": "ai_impact_on_jobs_2030_47d7dd3144f7",
            "row_count": 100,
        }

    agent = DataProfilerAgent(
        dataset_lookup_fn=dataset_lookup_fn,
        schema_context_builder_fn=schema_context_builder_fn,
    )

    result = agent.run(DataProfilerAgentInput(dataset_id=DATASET_ID))

    assert result.success is False
    assert result.profiling_status == "schema_context_build_failed"
    assert result.error_type == "SCHEMA_CONTEXT_BUILD_FAILED"
    assert "Missing required field(s)" in result.message
    assert "column_count" in result.message
    assert "schema_profile" in result.message


def test_output_contains_expected_structured_fields() -> None:
    def dataset_lookup_fn(dataset_id: str) -> dict[str, Any] | None:
        return sample_dataset()

    def schema_context_builder_fn(dataset_id: str) -> dict[str, Any] | None:
        return sample_schema_context()

    agent = DataProfilerAgent(
        dataset_lookup_fn=dataset_lookup_fn,
        schema_context_builder_fn=schema_context_builder_fn,
    )

    result = agent.run(
        {
            "dataset_id": DATASET_ID,
            "request_id": REQUEST_ID,
            "metadata": {"trace": "test"},
        }
    )

    result_dict = result.model_dump()

    expected_fields = {
        "success",
        "dataset_id",
        "table_name",
        "row_count",
        "column_count",
        "schema_profile",
        "schema_context",
        "profiling_status",
        "error_type",
        "message",
        "request_id",
        "metadata",
    }

    assert set(result_dict.keys()) == expected_fields


def test_agent_has_no_model_or_llm_dependency() -> None:
    constructor_signature = inspect.signature(DataProfilerAgent.__init__)

    forbidden_constructor_dependencies = {
        "llm",
        "llm_client",
        "model",
        "model_client",
        "openai_client",
        "langchain_client",
    }

    assert forbidden_constructor_dependencies.isdisjoint(
        constructor_signature.parameters.keys()
    )

    source = inspect.getsource(data_profiler_agent_module)

    forbidden_source_references = {
        "OpenAI",
        "ChatOpenAI",
        "LangChain",
        "generate_text",
        "llm_client",
    }

    for forbidden_reference in forbidden_source_references:
        assert forbidden_reference not in source