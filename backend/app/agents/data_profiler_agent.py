from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.dataset_registry import get_dataset_by_id
from app.services.schema_context_builder import build_schema_context


ProfilingStatus = Literal[
    "completed",
    "dataset_not_found",
    "missing_schema_profile",
    "schema_context_build_failed",
]

DataProfilerErrorType = Literal[
    "DATASET_NOT_FOUND",
    "MISSING_SCHEMA_PROFILE",
    "SCHEMA_CONTEXT_BUILD_FAILED",
]

DatasetLookupFn = Callable[[str], dict[str, Any] | None]
SchemaContextBuilderFn = Callable[[str], dict[str, Any] | None]


class DataProfilerAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(..., min_length=1)
    request_id: str | None = None
    metadata: dict[str, Any] | None = None


class DataProfilerAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    dataset_id: str
    table_name: str | None = None
    row_count: int | None = None
    column_count: int | None = None
    schema_profile: dict[str, Any] | None = None
    schema_context: dict[str, Any] | None = None
    profiling_status: ProfilingStatus
    error_type: DataProfilerErrorType | None = None
    message: str
    request_id: str | None = None
    metadata: dict[str, Any] | None = None


class DataProfilerAgent:
    REQUIRED_SCHEMA_CONTEXT_KEYS = (
        "dataset_id",
        "table_name",
        "row_count",
        "column_count",
        "schema_profile",
    )

    def __init__(
        self,
        dataset_lookup_fn: DatasetLookupFn = get_dataset_by_id,
        schema_context_builder_fn: SchemaContextBuilderFn = build_schema_context,
    ) -> None:
        self._dataset_lookup_fn = dataset_lookup_fn
        self._schema_context_builder_fn = schema_context_builder_fn

    def run(
        self,
        agent_input: DataProfilerAgentInput | dict[str, Any],
    ) -> DataProfilerAgentOutput:
        parsed_input = self._parse_input(agent_input)
        dataset_id = parsed_input.dataset_id.strip()

        dataset = self._dataset_lookup_fn(dataset_id)

        if dataset is None:
            return self._failure(
                agent_input=parsed_input,
                dataset_id=dataset_id,
                profiling_status="dataset_not_found",
                error_type="DATASET_NOT_FOUND",
                message="Dataset was not found in the dataset registry.",
            )

        schema_profile = dataset.get("schema_profile")

        if schema_profile is None:
            return self._failure(
                agent_input=parsed_input,
                dataset_id=dataset_id,
                profiling_status="missing_schema_profile",
                error_type="MISSING_SCHEMA_PROFILE",
                message="Dataset exists, but no schema profile is stored for it.",
            )

        try:
            schema_context = self._schema_context_builder_fn(dataset_id)
        except Exception:
            return self._failure(
                agent_input=parsed_input,
                dataset_id=dataset_id,
                profiling_status="schema_context_build_failed",
                error_type="SCHEMA_CONTEXT_BUILD_FAILED",
                message="Failed to build schema context for the dataset.",
            )

        if schema_context is None:
            return self._failure(
                agent_input=parsed_input,
                dataset_id=dataset_id,
                profiling_status="schema_context_build_failed",
                error_type="SCHEMA_CONTEXT_BUILD_FAILED",
                message="Schema context builder returned no context for the dataset.",
            )

        missing_context_keys = [
            key
            for key in self.REQUIRED_SCHEMA_CONTEXT_KEYS
            if schema_context.get(key) is None
        ]

        if missing_context_keys:
            missing_keys_text = ", ".join(missing_context_keys)

            return self._failure(
                agent_input=parsed_input,
                dataset_id=dataset_id,
                profiling_status="schema_context_build_failed",
                error_type="SCHEMA_CONTEXT_BUILD_FAILED",
                message=(
                    "Schema context is incomplete. "
                    f"Missing required field(s): {missing_keys_text}."
                ),
            )

        return DataProfilerAgentOutput(
            success=True,
            dataset_id=dataset_id,
            table_name=schema_context["table_name"],
            row_count=schema_context["row_count"],
            column_count=schema_context["column_count"],
            schema_profile=schema_context["schema_profile"],
            schema_context=schema_context,
            profiling_status="completed",
            error_type=None,
            message="Dataset profile and schema context resolved successfully.",
            request_id=parsed_input.request_id,
            metadata=parsed_input.metadata,
        )

    @staticmethod
    def _parse_input(
        agent_input: DataProfilerAgentInput | dict[str, Any],
    ) -> DataProfilerAgentInput:
        if isinstance(agent_input, DataProfilerAgentInput):
            return agent_input

        return DataProfilerAgentInput.model_validate(agent_input)

    @staticmethod
    def _failure(
        *,
        agent_input: DataProfilerAgentInput,
        dataset_id: str,
        profiling_status: ProfilingStatus,
        error_type: DataProfilerErrorType,
        message: str,
    ) -> DataProfilerAgentOutput:
        return DataProfilerAgentOutput(
            success=False,
            dataset_id=dataset_id,
            table_name=None,
            row_count=None,
            column_count=None,
            schema_profile=None,
            schema_context=None,
            profiling_status=profiling_status,
            error_type=error_type,
            message=message,
            request_id=agent_input.request_id,
            metadata=agent_input.metadata,
        )


__all__ = [
    "DataProfilerAgent",
    "DataProfilerAgentInput",
    "DataProfilerAgentOutput",
]