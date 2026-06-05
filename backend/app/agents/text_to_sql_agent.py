from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field

from app.services.schema_context_builder import build_schema_context

logger = logging.getLogger(__name__)


SQLGeneratorCallable = Callable[[str, dict[str, Any], str], str]
SchemaContextBuilderCallable = Callable[[str], dict[str, Any] | None]


class TextToSQLErrorType(str, Enum):
    MODEL_UNAVAILABLE = "model_unavailable"
    SCHEMA_CONTEXT_NOT_FOUND = "schema_context_not_found"
    INVALID_SCHEMA_CONTEXT = "invalid_schema_context"
    SQL_GENERATOR_UNAVAILABLE = "sql_generator_unavailable"
    SQL_GENERATION_FAILED = "sql_generation_failed"
    EMPTY_SQL_GENERATED = "empty_sql_generated"


class SchemaContextSource(str, Enum):
    PROVIDED = "provided"
    BUILT_FROM_DATASET_ID = "built_from_dataset_id"


class TextToSQLAgentInput(BaseModel):
    dataset_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)

    schema_context: dict[str, Any] | None = None

    model_available: bool = True
    request_id: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


class TextToSQLAgentOutput(BaseModel):
    success: bool

    dataset_id: str
    question: str
    sql: str | None = None

    model_required: bool = True
    model_available: bool

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

    This agent wraps the existing SQL generation service without duplicating
    SQL prompt construction or LLM call logic.

    Responsibilities:
    - Accept structured input.
    - Resolve schema context.
    - Respect model/API availability decisions.
    - Call the existing generate_sql_from_question service.
    - Return structured success/error output.
    - Add useful audit/debug metadata.

    Non-responsibilities:
    - SQL validation.
    - SQL execution.
    - Data-quality analysis.
    - Chart generation.
    - Answer formatting.
    """

    def __init__(
        self,
        sql_generator: SQLGeneratorCallable | None = None,
        schema_context_builder: SchemaContextBuilderCallable = build_schema_context,
    ) -> None:
        self.sql_generator = sql_generator
        self.schema_context_builder = schema_context_builder

    def generate(self, agent_input: TextToSQLAgentInput) -> TextToSQLAgentOutput:
        start_time = time.perf_counter()

        if not agent_input.model_available:
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                error_type=TextToSQLErrorType.MODEL_UNAVAILABLE,
                error_message=(
                    "Text-to-SQL generation requires an available LLM model/API, "
                    "but the model is currently unavailable."
                ),
            )

        schema_context, schema_context_source = self._resolve_schema_context(agent_input)

        if schema_context is None:
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                error_type=TextToSQLErrorType.SCHEMA_CONTEXT_NOT_FOUND,
                error_message=(
                    f"Schema context could not be found for dataset_id={agent_input.dataset_id!r}."
                ),
            )

        schema_validation_error = self._validate_schema_context(schema_context)

        if schema_validation_error is not None:
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                error_type=TextToSQLErrorType.INVALID_SCHEMA_CONTEXT,
                error_message=schema_validation_error,
                schema_context_source=schema_context_source,
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
                schema_context_source=schema_context_source,
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
                    schema_context_source=schema_context_source,
                    extra_metadata={
                        "table_name": table_name,
                    },
                )

            return TextToSQLAgentOutput(
                success=True,
                dataset_id=agent_input.dataset_id,
                question=agent_input.question,
                sql=generated_sql.strip(),
                model_available=agent_input.model_available,
                schema_context_source=schema_context_source,
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
                    "schema_context_available": True,
                },
            )

        except Exception as exc:
            logger.exception("Text-to-SQL generation failed.")

            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                error_type=TextToSQLErrorType.SQL_GENERATION_FAILED,
                error_message=str(exc),
                schema_context_source=schema_context_source,
                extra_metadata={
                    "table_name": table_name,
                    "exception_type": type(exc).__name__,
                },
            )

    def _resolve_schema_context(
        self,
        agent_input: TextToSQLAgentInput,
    ) -> tuple[dict[str, Any] | None, SchemaContextSource | None]:
        if agent_input.schema_context is not None:
            return agent_input.schema_context, SchemaContextSource.PROVIDED

        schema_context = self.schema_context_builder(agent_input.dataset_id)

        if schema_context is None:
            return None, None

        return schema_context, SchemaContextSource.BUILT_FROM_DATASET_ID

    def _resolve_sql_generator(self) -> SQLGeneratorCallable:
        if self.sql_generator is not None:
            return self.sql_generator

        from app.services.sql_generator import generate_sql_from_question

        return generate_sql_from_question

    @staticmethod
    def _validate_schema_context(schema_context: dict[str, Any]) -> str | None:
        table_name = schema_context.get("table_name")

        if not isinstance(table_name, str) or not table_name.strip():
            return "Schema context is missing a valid table_name."

        schema_profile = schema_context.get("schema_profile")

        if not isinstance(schema_profile, dict):
            return "Schema context is missing a valid schema_profile dictionary."

        columns = schema_profile.get("columns")

        if not isinstance(columns, list):
            return "Schema profile is missing a valid columns list."

        return None

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
            model_available=agent_input.model_available,
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