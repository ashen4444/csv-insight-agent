# backend/app/agents/query_executor_agent.py

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


QueryExecutorCallable = Callable[[str], dict[str, Any]]


class QueryExecutionStatus(str, Enum):
    SUCCEEDED = "execution_succeeded"
    BLOCKED = "execution_blocked"
    FAILED = "execution_failed"


class QueryExecutorErrorType(str, Enum):
    EMPTY_SQL = "empty_sql"
    UNSAFE_SQL = "unsafe_sql"
    VALIDATION_NOT_PASSED = "validation_not_passed"
    QUERY_EXECUTOR_UNAVAILABLE = "query_executor_unavailable"
    QUERY_EXECUTION_FAILED = "query_execution_failed"
    INVALID_EXECUTOR_RESPONSE = "invalid_executor_response"
    UNEXPECTED_EXECUTION_ERROR = "unexpected_execution_error"


class QueryExecutorAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    sql: str

    is_safe_to_execute: bool
    validation_status: str | None = None

    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryExecutorAgentOutput(BaseModel):
    success: bool

    dataset_id: str
    question: str
    sql: str | None = None

    executed: bool
    execution_status: QueryExecutionStatus

    results: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    execution_time_ms: float

    error_type: QueryExecutorErrorType | None = None
    error_message: str | None = None
    blocking_reason: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class QueryExecutorAgent:
    """
    Production-style Query Executor Agent wrapper.

    This agent wraps the existing query execution service without duplicating
    SQL validation, SQL safety rules, DuckDB execution logic, timeout handling,
    LIMIT enforcement, or result serialization.

    Responsibilities:
    - Accept structured input.
    - Refuse execution unless SQL has been marked safe by validation.
    - Optionally enforce that validation_status is valid when provided.
    - Call the existing execute_query service.
    - Return structured execution output.
    - Convert service failures into structured agent failures.
    - Expose metadata useful for audit/debugging and future orchestration.

    Non-responsibilities:
    - SQL generation.
    - SQL validation rules.
    - SQL rewriting.
    - Data-quality analysis.
    - Chart generation.
    - Final natural-language answer formatting.
    - LangGraph orchestration.
    """

    def __init__(
        self,
        query_executor: QueryExecutorCallable | None = None,
    ) -> None:
        self.query_executor = query_executor

    def execute(
        self,
        agent_input: QueryExecutorAgentInput,
    ) -> QueryExecutorAgentOutput:
        start_time = time.perf_counter()

        normalized_sql = agent_input.sql.strip()
        normalized_validation_status = self._normalize_validation_status(
            agent_input.validation_status
        )

        if not normalized_sql:
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                execution_status=QueryExecutionStatus.BLOCKED,
                error_type=QueryExecutorErrorType.EMPTY_SQL,
                error_message="Query execution skipped because SQL is empty.",
                blocking_reason="SQL is empty.",
                sql=None,
                normalized_validation_status=normalized_validation_status,
                extra_metadata={
                    "execution_attempted": False,
                    "guardrail_passed": False,
                },
            )

        if not agent_input.is_safe_to_execute:
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                execution_status=QueryExecutionStatus.BLOCKED,
                error_type=QueryExecutorErrorType.UNSAFE_SQL,
                error_message=(
                    "Query execution skipped because SQL was not marked safe "
                    "to execute."
                ),
                blocking_reason=(
                    "SQL was not marked safe to execute by the SQL Validator / "
                    "Guardrail Agent."
                ),
                sql=normalized_sql,
                normalized_validation_status=normalized_validation_status,
                extra_metadata={
                    "execution_attempted": False,
                    "guardrail_passed": False,
                },
            )

        if (
            normalized_validation_status is not None
            and normalized_validation_status != "valid"
        ):
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                execution_status=QueryExecutionStatus.BLOCKED,
                error_type=QueryExecutorErrorType.VALIDATION_NOT_PASSED,
                error_message=(
                    "Query execution skipped because SQL validation status "
                    "is not valid."
                ),
                blocking_reason=(
                    f"SQL validation status is {normalized_validation_status!r}, "
                    "not 'valid'."
                ),
                sql=normalized_sql,
                normalized_validation_status=normalized_validation_status,
                extra_metadata={
                    "execution_attempted": False,
                    "guardrail_passed": False,
                },
            )

        try:
            executor = self._resolve_query_executor()
        except Exception as exc:
            logger.exception("Query executor service could not be loaded.")

            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                execution_status=QueryExecutionStatus.FAILED,
                error_type=QueryExecutorErrorType.QUERY_EXECUTOR_UNAVAILABLE,
                error_message=str(exc),
                blocking_reason="Query executor service is unavailable.",
                sql=normalized_sql,
                normalized_validation_status=normalized_validation_status,
                extra_metadata={
                    "execution_attempted": False,
                    "exception_type": type(exc).__name__,
                    "guardrail_passed": True,
                },
            )

        try:
            execution_result = executor(normalized_sql)

            response_validation_error = self._validate_execution_result(
                execution_result
            )

            if response_validation_error is not None:
                return self._failure(
                    agent_input=agent_input,
                    start_time=start_time,
                    execution_status=QueryExecutionStatus.FAILED,
                    error_type=QueryExecutorErrorType.INVALID_EXECUTOR_RESPONSE,
                    error_message=response_validation_error,
                    blocking_reason=(
                        "Query execution service returned an invalid response."
                    ),
                    sql=normalized_sql,
                    normalized_validation_status=normalized_validation_status,
                    extra_metadata={
                        "execution_attempted": True,
                        "guardrail_passed": True,
                    },
                )

            executed_sql = execution_result["sql"]
            results = execution_result["results"]
            row_count = execution_result["row_count"]
            service_execution_time_ms = float(execution_result["execution_time_ms"])

            return QueryExecutorAgentOutput(
                success=True,
                dataset_id=agent_input.dataset_id,
                question=agent_input.question,
                sql=executed_sql,
                executed=True,
                execution_status=QueryExecutionStatus.SUCCEEDED,
                results=results,
                row_count=row_count,
                execution_time_ms=service_execution_time_ms,
                error_type=None,
                error_message=None,
                blocking_reason=None,
                metadata={
                    **agent_input.metadata,
                    "request_id": agent_input.request_id,
                    "agent": "QueryExecutorAgent",
                    "service": "execute_query",
                    "original_sql": normalized_sql,
                    "validation_status": normalized_validation_status,
                    "is_safe_to_execute": agent_input.is_safe_to_execute,
                    "guardrail_passed": True,
                    "execution_attempted": True,
                    "agent_execution_time_ms": self._elapsed_ms(start_time),
                    "service_returned_sql": executed_sql,
                    "safe_limit_may_have_been_applied": executed_sql != normalized_sql,
                },
            )

        except ValueError as exc:
            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                execution_status=QueryExecutionStatus.FAILED,
                error_type=QueryExecutorErrorType.QUERY_EXECUTION_FAILED,
                error_message=str(exc),
                blocking_reason="Query execution failed in the execution service.",
                sql=normalized_sql,
                normalized_validation_status=normalized_validation_status,
                extra_metadata={
                    "execution_attempted": True,
                    "exception_type": type(exc).__name__,
                    "guardrail_passed": True,
                },
            )

        except Exception as exc:
            logger.exception("Unexpected query execution error.")

            return self._failure(
                agent_input=agent_input,
                start_time=start_time,
                execution_status=QueryExecutionStatus.FAILED,
                error_type=QueryExecutorErrorType.UNEXPECTED_EXECUTION_ERROR,
                error_message=str(exc),
                blocking_reason=(
                    "Query execution failed due to an unexpected internal error."
                ),
                sql=normalized_sql,
                normalized_validation_status=normalized_validation_status,
                extra_metadata={
                    "execution_attempted": True,
                    "exception_type": type(exc).__name__,
                    "guardrail_passed": True,
                },
            )

    def _resolve_query_executor(self) -> QueryExecutorCallable:
        if self.query_executor is not None:
            return self.query_executor

        from app.services.query_executor import execute_query

        return execute_query

    def _failure(
        self,
        agent_input: QueryExecutorAgentInput,
        start_time: float,
        execution_status: QueryExecutionStatus,
        error_type: QueryExecutorErrorType,
        error_message: str,
        blocking_reason: str,
        sql: str | None,
        normalized_validation_status: str | None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> QueryExecutorAgentOutput:
        return QueryExecutorAgentOutput(
            success=False,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            sql=sql,
            executed=False,
            execution_status=execution_status,
            results=[],
            row_count=0,
            execution_time_ms=self._elapsed_ms(start_time),
            error_type=error_type,
            error_message=error_message,
            blocking_reason=blocking_reason,
            metadata={
                **agent_input.metadata,
                "request_id": agent_input.request_id,
                "agent": "QueryExecutorAgent",
                "service": "execute_query",
                "validation_status": normalized_validation_status,
                "is_safe_to_execute": agent_input.is_safe_to_execute,
                **(extra_metadata or {}),
            },
        )

    @staticmethod
    def _validate_execution_result(execution_result: Any) -> str | None:
        if not isinstance(execution_result, dict):
            return "Query executor response must be a dictionary."

        required_keys = ["sql", "row_count", "execution_time_ms", "results"]
        missing_keys = [
            key for key in required_keys
            if key not in execution_result
        ]

        if missing_keys:
            return f"Query executor response is missing key(s): {missing_keys}."

        sql = execution_result["sql"]
        row_count = execution_result["row_count"]
        execution_time_ms = execution_result["execution_time_ms"]
        results = execution_result["results"]

        if not isinstance(sql, str) or not sql.strip():
            return "Query executor response contains invalid sql."

        if not isinstance(row_count, int):
            return "Query executor response contains invalid row_count."

        if not isinstance(execution_time_ms, (int, float)):
            return "Query executor response contains invalid execution_time_ms."

        if not isinstance(results, list):
            return "Query executor response contains invalid results."

        for row in results:
            if not isinstance(row, dict):
                return "Query executor response results must contain dictionaries."

        return None

    @staticmethod
    def _normalize_validation_status(validation_status: Any) -> str | None:
        if validation_status is None:
            return None

        if isinstance(validation_status, Enum):
            status_value = validation_status.value
        else:
            status_value = str(validation_status)

        normalized_status = status_value.strip().lower()

        return normalized_status or None

    @staticmethod
    def _elapsed_ms(start_time: float) -> float:
        return round((time.perf_counter() - start_time) * 1000, 3)