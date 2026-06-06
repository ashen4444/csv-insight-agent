from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.services.schema_context_builder import build_schema_context

logger = logging.getLogger(__name__)


class SQLGeneratorCallable(Protocol):
    def __call__(
        self,
        table_name: str,
        schema_profile: dict[str, Any],
        question: str,
    ) -> str:
        ...


class SchemaContextBuilderCallable(Protocol):
    def __call__(self, dataset_id: str) -> dict[str, Any] | None:
        ...


class TextToSQLErrorType(str, Enum):
    SCHEMA_CONTEXT_NOT_FOUND = "schema_context_not_found"
    INVALID_SCHEMA_CONTEXT = "invalid_schema_context"
    SQL_GENERATOR_UNAVAILABLE = "sql_generator_unavailable"
    SQL_GENERATION_FAILED = "sql_generation_failed"
    EMPTY_SQL_GENERATED = "empty_sql_generated"


class SchemaContextSource(str, Enum):
    RESOLVED_FROM_DATASET_ID = "resolved_from_dataset_id"


class TextToSQLAgentInput(BaseModel):
    """
    Input accepted by the Text-to-SQL Agent.

    Important:
    - schema_context is intentionally NOT accepted.
    - schema_profile is intentionally NOT accepted.
    - The agent must resolve schema context internally from dataset_id.
    """

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)

    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TextToSQLAgentOutput(BaseModel):
    success: bool

    dataset_id: str
    question: str
    sql: str | None = None

    model_required: bool = True

    schema_context_source: SchemaContextSource | None = None

    error_type: TextToSQLErrorType | None = None
    error_message: str | None = None

    execution_time_ms: float
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class TextToSQLAgent:
    """
    Production-style Text-to-SQL Agent wrapper.

    Responsibilities:
    - Accept dataset_id and question only.
    - Resolve schema context internally from dataset_id.
    - Prevent caller-provided schema_context/schema_profile usage.
    - Validate schema context before SQL generation.
    - Call the existing SQL generation service.
    - Return structured success/error output.
    - Keep raw CSV rows away from the LLM.

    Non-responsibilities:
    - SQL validation.
    - SQL execution.
    - Data-quality analysis.
    - Chart generation.
    - Answer formatting.
    """

    RAW_ROW_PAYLOAD_KEYS = {
        "rows",
        "records",
        "raw_rows",
        "csv_rows",
        "dataframe",
    }

    def __init__(
        self,
        sql_generator: SQLGeneratorCallable | None = None,
        schema_context_builder: SchemaContextBuilderCallable = build_schema_context,
    ) -> None:
        self.sql_generator = sql_generator
        self.schema_context_builder = schema_context_builder

    def generate(self, agent_input: TextToSQLAgentInput) -> TextToSQLAgentOutput:
        start_time = time.perf_counter()

        schema_context = self.schema_context_builder(agent_input.dataset_id)

        if schema_context is None:
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                error_type=TextToSQLErrorType.SCHEMA_CONTEXT_NOT_FOUND,
                error_message=(
                    f"Schema context could not be resolved for "
                    f"dataset_id={agent_input.dataset_id!r}."
                ),
            )

        schema_validation_error = self._validate_schema_context(schema_context)

        if schema_validation_error is not None:
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                error_type=TextToSQLErrorType.INVALID_SCHEMA_CONTEXT,
                error_message=schema_validation_error,
                schema_context_source=SchemaContextSource.RESOLVED_FROM_DATASET_ID,
                extra_metadata={
                    "schema_context_keys": list(schema_context.keys()),
                },
            )

        table_name = schema_context["table_name"]
        schema_profile = schema_context["schema_profile"]

        try:
            sql_generator = self._resolve_sql_generator()
        except Exception as exc:
            logger.exception("SQL generator service could not be loaded.")

            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                error_type=TextToSQLErrorType.SQL_GENERATOR_UNAVAILABLE,
                error_message=str(exc),
                schema_context_source=SchemaContextSource.RESOLVED_FROM_DATASET_ID,
                extra_metadata={
                    "table_name": table_name,
                    "exception_type": type(exc).__name__,
                },
            )

        try:
            generated_sql = sql_generator(
                table_name=table_name,
                schema_profile=schema_profile,
                question=agent_input.question,
            )

            if not isinstance(generated_sql, str) or not generated_sql.strip():
                return self._failure(
                    agent_input=agent_input,
                    start_time=start_time,
                    error_type=TextToSQLErrorType.EMPTY_SQL_GENERATED,
                    error_message="SQL generator returned an empty SQL response.",
                    schema_context_source=SchemaContextSource.RESOLVED_FROM_DATASET_ID,
                    extra_metadata={
                        "table_name": table_name,
                    },
                )

            return TextToSQLAgentOutput(
                success=True,
                dataset_id=agent_input.dataset_id,
                question=agent_input.question,
                sql=generated_sql.strip(),
                schema_context_source=SchemaContextSource.RESOLVED_FROM_DATASET_ID,
                execution_time_ms=self._elapsed_ms(start_time),
                metadata={
                    **agent_input.metadata,
                    "request_id": agent_input.request_id,
                    "agent": "TextToSQLAgent",
                    "service": "generate_sql_from_question",
                    "table_name": table_name,
                    "row_count": schema_context.get("row_count"),
                    "column_count": schema_context.get("column_count"),
                    "schema_column_count": len(schema_profile.get("columns", [])),
                    "schema_context_source": SchemaContextSource.RESOLVED_FROM_DATASET_ID.value,
                    "raw_rows_sent_to_llm": False,
                },
            )

        except Exception as exc:
            logger.exception("Text-to-SQL generation failed.")

            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                error_type=TextToSQLErrorType.SQL_GENERATION_FAILED,
                error_message=str(exc),
                schema_context_source=SchemaContextSource.RESOLVED_FROM_DATASET_ID,
                extra_metadata={
                    "table_name": table_name,
                    "exception_type": type(exc).__name__,
                },
            )

    def _resolve_sql_generator(self) -> SQLGeneratorCallable:
        if self.sql_generator is not None:
            return self.sql_generator

        from app.services.sql_generator import generate_sql_from_question

        return generate_sql_from_question

    @classmethod
    def _validate_schema_context(cls, schema_context: dict[str, Any]) -> str | None:
        if cls._contains_raw_row_payload(schema_context):
            return (
                "Schema context contains raw row payload keys and cannot be used "
                "for LLM SQL generation."
            )

        table_name = schema_context.get("table_name")

        if not isinstance(table_name, str) or not table_name.strip():
            return "Schema context is missing a valid table_name."

        schema_profile = schema_context.get("schema_profile")

        if not isinstance(schema_profile, dict):
            return "Schema context is missing a valid schema_profile dictionary."

        if cls._contains_raw_row_payload(schema_profile):
            return (
                "Schema profile contains raw row payload keys and cannot be used "
                "for LLM SQL generation."
            )

        columns = schema_profile.get("columns")

        if not isinstance(columns, list):
            return "Schema profile is missing a valid columns list."

        return None

    @classmethod
    def _contains_raw_row_payload(cls, value: dict[str, Any]) -> bool:
        return any(key in value for key in cls.RAW_ROW_PAYLOAD_KEYS)

    def _failure(
        self,
        agent_input: TextToSQLAgentInput,
        start_time: float,
        error_type: TextToSQLErrorType,
        error_message: str,
        schema_context_source: SchemaContextSource | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> TextToSQLAgentOutput:
        return TextToSQLAgentOutput(
            success=False,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            sql=None,
            schema_context_source=schema_context_source,
            error_type=error_type,
            error_message=error_message,
            execution_time_ms=self._elapsed_ms(start_time),
            metadata={
                **agent_input.metadata,
                "request_id": agent_input.request_id,
                "agent": "TextToSQLAgent",
                **(extra_metadata or {}),
            },
        )

    @staticmethod
    def _elapsed_ms(start_time: float) -> float:
        return round((time.perf_counter() - start_time) * 1000, 3)