from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field

from app.services.schema_context_builder import build_schema_context

logger = logging.getLogger(__name__)


SQLValidatorCallable = Callable[[str, dict[str, Any]], None]
SchemaContextBuilderCallable = Callable[[str], dict[str, Any] | None]


class SQLValidationStatus(str, Enum):
    VALID = "valid"
    BLOCKED = "blocked"
    ERROR = "error"


class SQLValidationErrorType(str, Enum):
    SCHEMA_CONTEXT_NOT_FOUND = "schema_context_not_found"
    INVALID_SCHEMA_CONTEXT = "invalid_schema_context"
    EMPTY_SQL = "empty_sql"
    SQL_VALIDATION_FAILED = "sql_validation_failed"
    SQL_VALIDATOR_UNAVAILABLE = "sql_validator_unavailable"
    UNEXPECTED_VALIDATION_ERROR = "unexpected_validation_error"


class SQLValidatorSchemaContextSource(str, Enum):
    PROVIDED = "provided"
    BUILT_FROM_DATASET_ID = "built_from_dataset_id"


class SQLValidatorAgentInput(BaseModel):
    dataset_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    sql: str

    schema_context: dict[str, Any] | None = None

    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SQLValidatorAgentOutput(BaseModel):
    success: bool

    dataset_id: str
    question: str
    sql: str | None = None

    validation_status: SQLValidationStatus
    is_valid: bool
    is_safe_to_execute: bool

    schema_context_source: SQLValidatorSchemaContextSource | None = None

    error_type: SQLValidationErrorType | None = None
    error_message: str | None = None
    blocking_reason: str | None = None

    execution_time_ms: float
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SQLValidatorAgent:
    """
    Production-style SQL Validator / Guardrail Agent wrapper.

    This agent wraps the existing SQL validation service without duplicating
    SQL parsing, safety, table-reference, or column-reference validation logic.

    Responsibilities:
    - Accept structured input.
    - Resolve schema context.
    - Validate basic schema-context shape before calling the service.
    - Call the existing validate_sql service.
    - Convert exception-based validation failures into structured guardrail output.
    - Return metadata useful for audit/debugging.
    - Block unsafe SQL before execution.

    Non-responsibilities:
    - SQL generation.
    - SQL execution.
    - Data-quality analysis.
    - Chart generation.
    - Answer formatting.
    - LangGraph orchestration.
    """

    def __init__(
        self,
        sql_validator: SQLValidatorCallable | None = None,
        schema_context_builder: SchemaContextBuilderCallable = build_schema_context,
    ) -> None:
        self.sql_validator = sql_validator
        self.schema_context_builder = schema_context_builder

    def validate(
        self,
        agent_input: SQLValidatorAgentInput,
    ) -> SQLValidatorAgentOutput:
        start_time = time.perf_counter()

        normalized_sql = agent_input.sql.strip()

        if not normalized_sql:
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                validation_status=SQLValidationStatus.BLOCKED,
                error_type=SQLValidationErrorType.EMPTY_SQL,
                error_message="SQL validation failed because the generated SQL is empty.",
                blocking_reason="Generated SQL is empty.",
            )

        schema_context, schema_context_source = self._resolve_schema_context(agent_input)

        if schema_context is None:
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                validation_status=SQLValidationStatus.ERROR,
                error_type=SQLValidationErrorType.SCHEMA_CONTEXT_NOT_FOUND,
                error_message=(
                    f"Schema context could not be found for dataset_id={agent_input.dataset_id!r}."
                ),
                blocking_reason="SQL cannot be validated without schema context.",
                sql=normalized_sql,
            )

        schema_validation_error = self._validate_schema_context(schema_context)

        if schema_validation_error is not None:
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                validation_status=SQLValidationStatus.ERROR,
                error_type=SQLValidationErrorType.INVALID_SCHEMA_CONTEXT,
                error_message=schema_validation_error,
                blocking_reason="SQL cannot be validated because schema context is invalid.",
                schema_context_source=schema_context_source,
                sql=normalized_sql,
                extra_metadata={
                    "schema_context_keys": list(schema_context.keys()),
                },
            )

        table_name = schema_context["table_name"]
        schema_profile = schema_context["schema_profile"]

        try:
            validator = self._resolve_sql_validator()
        except Exception as exc:
            logger.exception("SQL validator service could not be loaded.")

            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                validation_status=SQLValidationStatus.ERROR,
                error_type=SQLValidationErrorType.SQL_VALIDATOR_UNAVAILABLE,
                error_message=str(exc),
                blocking_reason="SQL validator service is unavailable.",
                schema_context_source=schema_context_source,
                sql=normalized_sql,
                extra_metadata={
                    "table_name": table_name,
                    "exception_type": type(exc).__name__,
                },
            )

        try:
            validator(normalized_sql, schema_context)

            return SQLValidatorAgentOutput(
                success=True,
                dataset_id=agent_input.dataset_id,
                question=agent_input.question,
                sql=normalized_sql,
                validation_status=SQLValidationStatus.VALID,
                is_valid=True,
                is_safe_to_execute=True,
                schema_context_source=schema_context_source,
                error_type=None,
                error_message=None,
                blocking_reason=None,
                execution_time_ms=self._elapsed_ms(start_time),
                metadata={
                    **agent_input.metadata,
                    "request_id": agent_input.request_id,
                    "agent": "SQLValidatorAgent",
                    "service": "validate_sql",
                    "table_name": table_name,
                    "row_count": schema_context.get("row_count"),
                    "column_count": schema_context.get("column_count"),
                    "schema_column_count": self._count_schema_columns(schema_profile),
                    "schema_context_available": True,
                    "guardrail_passed": True,
                },
            )

        except ValueError as exc:
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                validation_status=SQLValidationStatus.BLOCKED,
                error_type=SQLValidationErrorType.SQL_VALIDATION_FAILED,
                error_message=str(exc),
                blocking_reason=str(exc),
                schema_context_source=schema_context_source,
                sql=normalized_sql,
                extra_metadata={
                    "table_name": table_name,
                    "exception_type": type(exc).__name__,
                    "guardrail_passed": False,
                },
            )

        except Exception as exc:
            logger.exception("Unexpected SQL validation error.")

            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                validation_status=SQLValidationStatus.ERROR,
                error_type=SQLValidationErrorType.UNEXPECTED_VALIDATION_ERROR,
                error_message=str(exc),
                blocking_reason="SQL validation failed due to an unexpected internal error.",
                schema_context_source=schema_context_source,
                sql=normalized_sql,
                extra_metadata={
                    "table_name": table_name,
                    "exception_type": type(exc).__name__,
                    "guardrail_passed": False,
                },
            )

    def _resolve_schema_context(
        self,
        agent_input: SQLValidatorAgentInput,
    ) -> tuple[dict[str, Any] | None, SQLValidatorSchemaContextSource | None]:
        if agent_input.schema_context is not None:
            return agent_input.schema_context, SQLValidatorSchemaContextSource.PROVIDED

        schema_context = self.schema_context_builder(agent_input.dataset_id)

        if schema_context is None:
            return None, None

        return schema_context, SQLValidatorSchemaContextSource.BUILT_FROM_DATASET_ID

    def _resolve_sql_validator(self) -> SQLValidatorCallable:
        if self.sql_validator is not None:
            return self.sql_validator

        from app.services.sql_validator import validate_sql

        return validate_sql

    @staticmethod
    def _validate_schema_context(schema_context: dict[str, Any]) -> str | None:
        table_name = schema_context.get("table_name")

        if not isinstance(table_name, str) or not table_name.strip():
            return "Schema context is missing a valid table_name."

        schema_profile = schema_context.get("schema_profile")

        if not isinstance(schema_profile, dict):
            return "Schema context is missing a valid schema_profile dictionary."

        columns = schema_profile.get("columns")

        if not isinstance(columns, list | dict):
            return "Schema profile is missing valid columns metadata."

        return None

    def _failure(
        self,
        agent_input: SQLValidatorAgentInput,
        start_time: float,
        validation_status: SQLValidationStatus,
        error_type: SQLValidationErrorType,
        error_message: str,
        blocking_reason: str,
        schema_context_source: SQLValidatorSchemaContextSource | None = None,
        sql: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> SQLValidatorAgentOutput:
        return SQLValidatorAgentOutput(
            success=False,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            sql=sql,
            validation_status=validation_status,
            is_valid=False,
            is_safe_to_execute=False,
            schema_context_source=schema_context_source,
            error_type=error_type,
            error_message=error_message,
            blocking_reason=blocking_reason,
            execution_time_ms=self._elapsed_ms(start_time),
            metadata={
                **agent_input.metadata,
                "request_id": agent_input.request_id,
                "agent": "SQLValidatorAgent",
                **(extra_metadata or {}),
            },
        )

    @staticmethod
    def _count_schema_columns(schema_profile: dict[str, Any]) -> int:
        columns = schema_profile.get("columns")

        if isinstance(columns, list | dict):
            return len(columns)

        return 0

    @staticmethod
    def _elapsed_ms(start_time: float) -> float:
        return round((time.perf_counter() - start_time) * 1000, 3)