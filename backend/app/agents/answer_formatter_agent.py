# backend/app/agents/answer_formatter_agent.py

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class AnswerResponseStatus(str, Enum):
    READY = "answer_ready"
    READY_WITH_WARNING = "answer_ready_with_warning"
    NO_RESULTS = "no_results"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    NEEDS_CLARIFICATION = "needs_clarification"


class AnswerResponseType(str, Enum):
    TEXT_ANSWER = "text_answer"
    TABLE_ANSWER = "table_answer"
    CHART_ANSWER = "chart_answer"
    TEXT_WITH_TABLE = "text_with_table"
    TEXT_WITH_CHART = "text_with_chart"
    TEXT_WITH_TABLE_AND_CHART = "text_with_table_and_chart"
    ERROR_MESSAGE = "error_message"
    CLARIFICATION_MESSAGE = "clarification_message"
    UNSUPPORTED_MESSAGE = "unsupported_message"


class AnswerFormatterErrorType(str, Enum):
    UNSUPPORTED_QUERY = "unsupported_query"
    NEEDS_CLARIFICATION = "needs_clarification"
    ROUTING_BLOCKED = "routing_blocked"
    SQL_GENERATION_FAILED = "sql_generation_failed"
    SQL_VALIDATION_BLOCKED = "sql_validation_blocked"
    SQL_VALIDATION_FAILED = "sql_validation_failed"
    EXECUTION_BLOCKED = "execution_blocked"
    EXECUTION_FAILED = "execution_failed"
    DATA_QUALITY_BLOCKED = "data_quality_blocked"
    DATA_QUALITY_FAILED = "data_quality_failed"
    UNEXPECTED_FORMATTING_ERROR = "unexpected_formatting_error"


class AnswerWarningSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AnswerRecommendationPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AnswerWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warning_type: str
    severity: AnswerWarningSeverity
    message: str

    source: str
    recommendation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnswerRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_type: str
    priority: AnswerRecommendationPriority
    message: str

    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnswerFormatterAgentInput(BaseModel):
    """
    Flattened formatter input.

    This input is intentionally compatible with serialized upstream agent
    outputs and future LangGraph state.

    Important:
    - schema_context is intentionally NOT accepted.
    - schema_profile is intentionally NOT accepted.
    - table_name is intentionally NOT accepted.
    - allowed_columns is intentionally NOT accepted.
    """

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    request_id: str | None = None

    primary_intent: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    routing_confidence: float | None = None
    routing_reason: str | None = None
    routing_source: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    is_routable: bool = True
    routing_blocking_reason: str | None = None
    unsupported_reason: str | None = None

    sql: str | None = None

    sql_generation_success: bool | None = None
    sql_generation_error_type: str | None = None
    sql_generation_error_message: str | None = None

    validation_success: bool | None = None
    validation_status: str | None = None
    is_valid: bool | None = None
    is_safe_to_execute: bool | None = None
    validation_error_type: str | None = None
    validation_error_message: str | None = None
    validation_blocking_reason: str | None = None

    execution_success: bool | None = None
    execution_status: str | None = None
    executed: bool | None = None
    results: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int | None = Field(default=None, ge=0)
    execution_time_ms: float | None = Field(default=None, ge=0)
    execution_error_type: str | None = None
    execution_error_message: str | None = None
    execution_blocking_reason: str | None = None

    data_quality_success: bool | None = None
    quality_status: str | None = None
    is_result_usable: bool | None = None
    is_result_empty: bool | None = None
    is_result_too_large: bool | None = None
    has_null_warnings: bool | None = None
    has_duplicate_warnings: bool | None = None
    has_visualization_warnings: bool | None = None
    quality_warnings: list[Any] = Field(default_factory=list)
    quality_recommendations: list[Any] = Field(default_factory=list)
    quality_error_type: str | None = None
    quality_error_message: str | None = None
    quality_blocking_reason: str | None = None

    chart_success: bool | None = None
    chart_generation_status: str | None = None
    chart_generation_enabled: bool | None = None
    chart_type: str | None = None
    selected_chart_type: str | None = None
    requested_chart_type: str | None = None
    recommended_chart_type: str | None = None
    chart_payload: dict[str, Any] | None = None
    chart_warning: Any | None = None
    chart_warnings: list[Any] = Field(default_factory=list)
    is_chart_available: bool | None = None
    is_chart_recommended: bool | None = None
    chart_error_type: str | None = None
    chart_error_message: str | None = None
    chart_blocking_reason: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


class AnswerFormatterAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool

    dataset_id: str
    question: str

    response_status: AnswerResponseStatus
    response_type: AnswerResponseType

    message: str
    summary: str | None = None

    display_results: list[dict[str, Any]] = Field(default_factory=list)
    display_result_count: int = Field(default=0, ge=0)
    display_columns: list[str] = Field(default_factory=list)

    chart_available: bool
    chart_type: str | None = None
    chart_payload: dict[str, Any] | None = None

    warnings: list[AnswerWarning] = Field(default_factory=list)
    recommendations: list[AnswerRecommendation] = Field(default_factory=list)

    technical_details: dict[str, Any] = Field(default_factory=dict)

    error_type: AnswerFormatterErrorType | None = None
    error_message: str | None = None
    blocking_reason: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class AnswerFormatterAgent:
    """
    Production-style Answer Formatter Agent wrapper.

    Responsibilities:
    - Convert structured upstream agent outputs into a final response object.
    - Separate user-facing message, display data, chart payload, warnings,
      recommendations, and technical metadata.
    - Preserve blocking/failure reasons instead of hiding them.
    - Include chart payload only when Chart Agent produced one.
    - Include Data Quality Agent warnings and recommendations where relevant.

    Non-responsibilities:
    - SQL generation.
    - SQL validation.
    - Query execution.
    - Data cleaning or mutation.
    - Chart payload generation.
    - Chart rendering.
    - LangGraph orchestration.
    - LLM calls.
    """

    def format(
        self,
        agent_input: AnswerFormatterAgentInput,
    ) -> AnswerFormatterAgentOutput:
        return self.generate_response(agent_input)

    def generate_response(
        self,
        agent_input: AnswerFormatterAgentInput,
    ) -> AnswerFormatterAgentOutput:
        start_time = time.perf_counter()

        try:
            if self._is_unsupported_query(agent_input):
                return self._unsupported_output(
                    agent_input=agent_input,
                    start_time=start_time,
                )

            if agent_input.needs_clarification:
                return self._clarification_output(
                    agent_input=agent_input,
                    start_time=start_time,
                )

            if not agent_input.is_routable:
                return self._blocked_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    error_type=AnswerFormatterErrorType.ROUTING_BLOCKED,
                    error_message=(
                        agent_input.routing_blocking_reason
                        or "The request could not be routed to a supported workflow."
                    ),
                    blocking_reason=(
                        agent_input.routing_blocking_reason
                        or "Routing policy blocked this request."
                    ),
                )

            sql_generation_error = self._sql_generation_error(agent_input)
            if sql_generation_error is not None:
                return self._failed_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    error_type=AnswerFormatterErrorType.SQL_GENERATION_FAILED,
                    error_message=sql_generation_error,
                    blocking_reason=(
                        "The system could not generate SQL for this question."
                    ),
                )

            validation_error_type = self._validation_error_type(agent_input)
            if validation_error_type is not None:
                return self._blocked_or_failed_validation_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    error_type=validation_error_type,
                )

            execution_error_type = self._execution_error_type(agent_input)
            if execution_error_type is not None:
                return self._blocked_or_failed_execution_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    error_type=execution_error_type,
                )

            data_quality_error_type = self._data_quality_error_type(agent_input)
            if data_quality_error_type is not None:
                return self._blocked_or_failed_quality_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    error_type=data_quality_error_type,
                )

            row_count = self._resolve_row_count(agent_input)
            warnings = self._collect_warnings(agent_input)
            recommendations = self._collect_recommendations(agent_input)

            chart_warning = self._chart_unavailable_warning(agent_input)
            if chart_warning is not None:
                warnings.append(chart_warning)

            if self._is_no_results(agent_input, row_count):
                return self._no_results_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    warnings=warnings,
                    recommendations=recommendations,
                )

            chart_available = self._has_chart_payload(agent_input)
            display_results = self._display_results(agent_input)
            display_columns = self._display_columns(display_results)

            response_status = (
                AnswerResponseStatus.READY_WITH_WARNING
                if warnings
                else AnswerResponseStatus.READY
            )

            response_type = self._resolve_response_type(
                has_results=bool(display_results),
                chart_available=chart_available,
            )

            message = self._success_message(
                row_count=row_count,
                has_results=bool(display_results),
                chart_available=chart_available,
                chart_type=agent_input.chart_type
                or agent_input.selected_chart_type,
                has_warnings=bool(warnings),
                chart_generation_status=self._normalize_status(
                    agent_input.chart_generation_status
                ),
            )

            return AnswerFormatterAgentOutput(
                success=True,
                dataset_id=agent_input.dataset_id,
                question=agent_input.question,
                response_status=response_status,
                response_type=response_type,
                message=message,
                summary=self._summary(
                    row_count=row_count,
                    chart_available=chart_available,
                    warning_count=len(warnings),
                ),
                display_results=display_results,
                display_result_count=len(display_results),
                display_columns=display_columns,
                chart_available=chart_available,
                chart_type=(
                    agent_input.chart_type
                    or agent_input.selected_chart_type
                ),
                chart_payload=(
                    agent_input.chart_payload
                    if chart_available
                    else None
                ),
                warnings=warnings,
                recommendations=recommendations,
                technical_details=self._technical_details(agent_input),
                error_type=None,
                error_message=None,
                blocking_reason=None,
                metadata=self._base_metadata(
                    agent_input=agent_input,
                    start_time=start_time,
                    extra_metadata={
                        "formatted_successfully": True,
                        "warning_count": len(warnings),
                        "recommendation_count": len(recommendations),
                    },
                ),
            )

        except Exception as exc:
            logger.exception("Unexpected Answer Formatter Agent error.")

            return AnswerFormatterAgentOutput(
                success=False,
                dataset_id=agent_input.dataset_id,
                question=agent_input.question,
                response_status=AnswerResponseStatus.FAILED,
                response_type=AnswerResponseType.ERROR_MESSAGE,
                message=(
                    "The answer could not be formatted because of an unexpected "
                    "internal error."
                ),
                summary=None,
                display_results=[],
                display_result_count=0,
                display_columns=[],
                chart_available=False,
                chart_type=None,
                chart_payload=None,
                warnings=[],
                recommendations=[],
                technical_details=self._technical_details(agent_input),
                error_type=AnswerFormatterErrorType.UNEXPECTED_FORMATTING_ERROR,
                error_message=str(exc),
                blocking_reason="Unexpected answer formatting failure.",
                metadata=self._base_metadata(
                    agent_input=agent_input,
                    start_time=start_time,
                    extra_metadata={
                        "formatted_successfully": False,
                        "exception_type": type(exc).__name__,
                    },
                ),
            )

    def _unsupported_output(
        self,
        *,
        agent_input: AnswerFormatterAgentInput,
        start_time: float,
    ) -> AnswerFormatterAgentOutput:
        reason = (
            agent_input.unsupported_reason
            or agent_input.routing_blocking_reason
            or "unsupported_query"
        )

        message = (
            "This request is outside the supported CSV analysis workflow. "
            "Please ask a question about the uploaded CSV dataset."
        )

        return AnswerFormatterAgentOutput(
            success=False,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            response_status=AnswerResponseStatus.UNSUPPORTED,
            response_type=AnswerResponseType.UNSUPPORTED_MESSAGE,
            message=message,
            summary=None,
            display_results=[],
            display_result_count=0,
            display_columns=[],
            chart_available=False,
            chart_type=None,
            chart_payload=None,
            warnings=[
                AnswerWarning(
                    warning_type="unsupported_query",
                    severity=AnswerWarningSeverity.INFO,
                    message=message,
                    source="intent_router_agent",
                    recommendation=(
                        "Ask a question related to the uploaded CSV dataset."
                    ),
                    metadata={
                        "unsupported_reason": reason,
                    },
                )
            ],
            recommendations=[],
            technical_details=self._technical_details(agent_input),
            error_type=AnswerFormatterErrorType.UNSUPPORTED_QUERY,
            error_message=reason,
            blocking_reason=(
                agent_input.routing_blocking_reason
                or "The request is outside the CSV analysis system scope."
            ),
            metadata=self._base_metadata(
                agent_input=agent_input,
                start_time=start_time,
                extra_metadata={
                    "formatted_successfully": True,
                },
            ),
        )

    def _clarification_output(
        self,
        *,
        agent_input: AnswerFormatterAgentInput,
        start_time: float,
    ) -> AnswerFormatterAgentOutput:
        message = (
            agent_input.clarification_question
            or "Could you clarify what you want to analyze from the CSV dataset?"
        )

        return AnswerFormatterAgentOutput(
            success=False,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            response_status=AnswerResponseStatus.NEEDS_CLARIFICATION,
            response_type=AnswerResponseType.CLARIFICATION_MESSAGE,
            message=message,
            summary=None,
            display_results=[],
            display_result_count=0,
            display_columns=[],
            chart_available=False,
            chart_type=None,
            chart_payload=None,
            warnings=[],
            recommendations=[],
            technical_details=self._technical_details(agent_input),
            error_type=AnswerFormatterErrorType.NEEDS_CLARIFICATION,
            error_message=message,
            blocking_reason="The router requires clarification before execution.",
            metadata=self._base_metadata(
                agent_input=agent_input,
                start_time=start_time,
                extra_metadata={
                    "formatted_successfully": True,
                },
            ),
        )

    def _blocked_output(
        self,
        *,
        agent_input: AnswerFormatterAgentInput,
        start_time: float,
        error_type: AnswerFormatterErrorType,
        error_message: str,
        blocking_reason: str,
    ) -> AnswerFormatterAgentOutput:
        return AnswerFormatterAgentOutput(
            success=False,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            response_status=AnswerResponseStatus.BLOCKED,
            response_type=AnswerResponseType.ERROR_MESSAGE,
            message=error_message,
            summary=None,
            display_results=[],
            display_result_count=0,
            display_columns=[],
            chart_available=False,
            chart_type=None,
            chart_payload=None,
            warnings=[
                AnswerWarning(
                    warning_type=error_type.value,
                    severity=AnswerWarningSeverity.CRITICAL,
                    message=error_message,
                    source="answer_formatter_agent",
                    recommendation=blocking_reason,
                    metadata={
                        "error_type": error_type.value,
                    },
                )
            ],
            recommendations=[],
            technical_details=self._technical_details(agent_input),
            error_type=error_type,
            error_message=error_message,
            blocking_reason=blocking_reason,
            metadata=self._base_metadata(
                agent_input=agent_input,
                start_time=start_time,
                extra_metadata={
                    "formatted_successfully": True,
                },
            ),
        )

    def _failed_output(
        self,
        *,
        agent_input: AnswerFormatterAgentInput,
        start_time: float,
        error_type: AnswerFormatterErrorType,
        error_message: str,
        blocking_reason: str,
    ) -> AnswerFormatterAgentOutput:
        return AnswerFormatterAgentOutput(
            success=False,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            response_status=AnswerResponseStatus.FAILED,
            response_type=AnswerResponseType.ERROR_MESSAGE,
            message=error_message,
            summary=None,
            display_results=[],
            display_result_count=0,
            display_columns=[],
            chart_available=False,
            chart_type=None,
            chart_payload=None,
            warnings=[
                AnswerWarning(
                    warning_type=error_type.value,
                    severity=AnswerWarningSeverity.CRITICAL,
                    message=error_message,
                    source="answer_formatter_agent",
                    recommendation=blocking_reason,
                    metadata={
                        "error_type": error_type.value,
                    },
                )
            ],
            recommendations=[],
            technical_details=self._technical_details(agent_input),
            error_type=error_type,
            error_message=error_message,
            blocking_reason=blocking_reason,
            metadata=self._base_metadata(
                agent_input=agent_input,
                start_time=start_time,
                extra_metadata={
                    "formatted_successfully": True,
                },
            ),
        )

    def _blocked_or_failed_validation_output(
        self,
        *,
        agent_input: AnswerFormatterAgentInput,
        start_time: float,
        error_type: AnswerFormatterErrorType,
    ) -> AnswerFormatterAgentOutput:
        reason = (
            agent_input.validation_blocking_reason
            or agent_input.validation_error_message
            or "SQL validation did not pass."
        )

        message = (
            "I could not run this query because the generated SQL did not pass "
            f"validation. Reason: {reason}"
        )

        if error_type == AnswerFormatterErrorType.SQL_VALIDATION_BLOCKED:
            return self._blocked_output(
                agent_input=agent_input,
                start_time=start_time,
                error_type=error_type,
                error_message=message,
                blocking_reason=reason,
            )

        return self._failed_output(
            agent_input=agent_input,
            start_time=start_time,
            error_type=error_type,
            error_message=message,
            blocking_reason=reason,
        )

    def _blocked_or_failed_execution_output(
        self,
        *,
        agent_input: AnswerFormatterAgentInput,
        start_time: float,
        error_type: AnswerFormatterErrorType,
    ) -> AnswerFormatterAgentOutput:
        reason = (
            agent_input.execution_blocking_reason
            or agent_input.execution_error_message
            or "Query execution did not succeed."
        )

        message = f"The query could not be executed. Reason: {reason}"

        if error_type == AnswerFormatterErrorType.EXECUTION_BLOCKED:
            return self._blocked_output(
                agent_input=agent_input,
                start_time=start_time,
                error_type=error_type,
                error_message=message,
                blocking_reason=reason,
            )

        return self._failed_output(
            agent_input=agent_input,
            start_time=start_time,
            error_type=error_type,
            error_message=message,
            blocking_reason=reason,
        )

    def _blocked_or_failed_quality_output(
        self,
        *,
        agent_input: AnswerFormatterAgentInput,
        start_time: float,
        error_type: AnswerFormatterErrorType,
    ) -> AnswerFormatterAgentOutput:
        reason = (
            agent_input.quality_blocking_reason
            or agent_input.quality_error_message
            or "Data quality checks did not pass."
        )

        message = (
            "The query ran, but the result is not safe to present because data "
            f"quality checks did not pass. Reason: {reason}"
        )

        if error_type == AnswerFormatterErrorType.DATA_QUALITY_BLOCKED:
            return self._blocked_output(
                agent_input=agent_input,
                start_time=start_time,
                error_type=error_type,
                error_message=message,
                blocking_reason=reason,
            )

        return self._failed_output(
            agent_input=agent_input,
            start_time=start_time,
            error_type=error_type,
            error_message=message,
            blocking_reason=reason,
        )

    def _no_results_output(
        self,
        *,
        agent_input: AnswerFormatterAgentInput,
        start_time: float,
        warnings: list[AnswerWarning],
        recommendations: list[AnswerRecommendation],
    ) -> AnswerFormatterAgentOutput:
        message = "The query ran successfully, but it did not return any rows."

        return AnswerFormatterAgentOutput(
            success=True,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            response_status=AnswerResponseStatus.NO_RESULTS,
            response_type=AnswerResponseType.TEXT_ANSWER,
            message=message,
            summary="No matching rows were found.",
            display_results=[],
            display_result_count=0,
            display_columns=[],
            chart_available=False,
            chart_type=None,
            chart_payload=None,
            warnings=warnings,
            recommendations=recommendations,
            technical_details=self._technical_details(agent_input),
            error_type=None,
            error_message=None,
            blocking_reason=None,
            metadata=self._base_metadata(
                agent_input=agent_input,
                start_time=start_time,
                extra_metadata={
                    "formatted_successfully": True,
                    "warning_count": len(warnings),
                    "recommendation_count": len(recommendations),
                },
            ),
        )

    @staticmethod
    def _is_unsupported_query(agent_input: AnswerFormatterAgentInput) -> bool:
        primary_intent = AnswerFormatterAgent._normalize_status(
            agent_input.primary_intent
        )

        return (
            primary_intent == "unsupported_query"
            or agent_input.unsupported_reason is not None
        )

    @staticmethod
    def _sql_generation_error(
        agent_input: AnswerFormatterAgentInput,
    ) -> str | None:
        if agent_input.sql_generation_success is False:
            return (
                agent_input.sql_generation_error_message
                or "SQL generation failed."
            )

        if agent_input.sql_generation_error_type is not None:
            return (
                agent_input.sql_generation_error_message
                or agent_input.sql_generation_error_type
            )

        return None

    @staticmethod
    def _validation_error_type(
        agent_input: AnswerFormatterAgentInput,
    ) -> AnswerFormatterErrorType | None:
        validation_status = AnswerFormatterAgent._normalize_status(
            agent_input.validation_status
        )

        if validation_status == "blocked":
            return AnswerFormatterErrorType.SQL_VALIDATION_BLOCKED

        if validation_status == "error":
            return AnswerFormatterErrorType.SQL_VALIDATION_FAILED

        if agent_input.validation_success is False:
            if agent_input.is_safe_to_execute is False:
                return AnswerFormatterErrorType.SQL_VALIDATION_BLOCKED

            return AnswerFormatterErrorType.SQL_VALIDATION_FAILED

        if agent_input.is_valid is False or agent_input.is_safe_to_execute is False:
            return AnswerFormatterErrorType.SQL_VALIDATION_BLOCKED

        return None

    @staticmethod
    def _execution_error_type(
        agent_input: AnswerFormatterAgentInput,
    ) -> AnswerFormatterErrorType | None:
        execution_status = AnswerFormatterAgent._normalize_status(
            agent_input.execution_status
        )

        if execution_status == "execution_blocked":
            return AnswerFormatterErrorType.EXECUTION_BLOCKED

        if execution_status == "execution_failed":
            return AnswerFormatterErrorType.EXECUTION_FAILED

        if agent_input.execution_success is False:
            if agent_input.executed is False:
                return AnswerFormatterErrorType.EXECUTION_BLOCKED

            return AnswerFormatterErrorType.EXECUTION_FAILED

        if agent_input.executed is False:
            return AnswerFormatterErrorType.EXECUTION_BLOCKED

        return None

    @staticmethod
    def _data_quality_error_type(
        agent_input: AnswerFormatterAgentInput,
    ) -> AnswerFormatterErrorType | None:
        quality_status = AnswerFormatterAgent._normalize_status(
            agent_input.quality_status
        )

        if agent_input.is_result_usable is False:
            return AnswerFormatterErrorType.DATA_QUALITY_BLOCKED

        if quality_status == "quality_failed":
            return AnswerFormatterErrorType.DATA_QUALITY_FAILED

        if (
            agent_input.data_quality_success is False
            and quality_status == "quality_not_evaluated"
            and agent_input.execution_success is not False
        ):
            return AnswerFormatterErrorType.DATA_QUALITY_FAILED

        return None

    @staticmethod
    def _resolve_row_count(agent_input: AnswerFormatterAgentInput) -> int:
        if agent_input.row_count is not None:
            return agent_input.row_count

        return len(agent_input.results)

    @staticmethod
    def _is_no_results(
        agent_input: AnswerFormatterAgentInput,
        row_count: int,
    ) -> bool:
        if agent_input.is_result_empty is True:
            return True

        execution_status = AnswerFormatterAgent._normalize_status(
            agent_input.execution_status
        )

        return (
            execution_status == "execution_succeeded"
            and row_count == 0
        )

    @staticmethod
    def _has_chart_payload(agent_input: AnswerFormatterAgentInput) -> bool:
        chart_status = AnswerFormatterAgent._normalize_status(
            agent_input.chart_generation_status
        )

        return (
            agent_input.is_chart_available is True
            and agent_input.chart_payload is not None
            and chart_status in {
                "chart_generated",
                "chart_generated_with_warning",
            }
        )

    @staticmethod
    def _display_results(
        agent_input: AnswerFormatterAgentInput,
    ) -> list[dict[str, Any]]:
        if not agent_input.results:
            return []

        if agent_input.is_result_usable is False:
            return []

        return agent_input.results

    @staticmethod
    def _display_columns(
        display_results: list[dict[str, Any]],
    ) -> list[str]:
        columns: list[str] = []

        for row in display_results:
            for column in row.keys():
                if column not in columns:
                    columns.append(column)

        return columns

    @staticmethod
    def _resolve_response_type(
        *,
        has_results: bool,
        chart_available: bool,
    ) -> AnswerResponseType:
        if has_results and chart_available:
            return AnswerResponseType.TEXT_WITH_TABLE_AND_CHART

        if has_results:
            return AnswerResponseType.TEXT_WITH_TABLE

        if chart_available:
            return AnswerResponseType.TEXT_WITH_CHART

        return AnswerResponseType.TEXT_ANSWER

    @staticmethod
    def _success_message(
        *,
        row_count: int,
        has_results: bool,
        chart_available: bool,
        chart_type: str | None,
        has_warnings: bool,
        chart_generation_status: str | None,
    ) -> str:
        row_label = "row" if row_count == 1 else "rows"

        if has_results:
            message = f"I found {row_count} {row_label} for your query."
        else:
            message = "The answer is ready."

        if chart_available:
            if chart_type:
                message += f" A {chart_type} chart is also available."
            else:
                message += " A chart is also available."

        if (
            chart_generation_status in {
                "chart_blocked",
                "chart_unavailable",
                "chart_failed",
            }
            and not chart_available
        ):
            message += " A chart was requested, but it could not be generated."

        if has_warnings:
            message += " Please review the warnings before using the result."

        return message

    @staticmethod
    def _summary(
        *,
        row_count: int,
        chart_available: bool,
        warning_count: int,
    ) -> str:
        summary_parts = [f"Returned rows: {row_count}."]

        if chart_available:
            summary_parts.append("Chart payload is available.")
        else:
            summary_parts.append("No chart payload is available.")

        summary_parts.append(f"Warnings: {warning_count}.")

        return " ".join(summary_parts)

    def _collect_warnings(
        self,
        agent_input: AnswerFormatterAgentInput,
    ) -> list[AnswerWarning]:
        warnings: list[AnswerWarning] = []

        for warning in agent_input.quality_warnings:
            normalized_warning = self._warning_from_any(
                warning,
                default_source="data_quality_agent",
            )
            if normalized_warning is not None:
                warnings.append(normalized_warning)

        if agent_input.chart_warning is not None:
            normalized_chart_warning = self._warning_from_any(
                agent_input.chart_warning,
                default_source="chart_agent",
            )
            if normalized_chart_warning is not None:
                warnings.append(normalized_chart_warning)

        for warning in agent_input.chart_warnings:
            normalized_warning = self._warning_from_any(
                warning,
                default_source="chart_agent",
            )
            if (
                normalized_warning is not None
                and normalized_warning not in warnings
            ):
                warnings.append(normalized_warning)

        return warnings

    def _collect_recommendations(
        self,
        agent_input: AnswerFormatterAgentInput,
    ) -> list[AnswerRecommendation]:
        recommendations: list[AnswerRecommendation] = []

        for recommendation in agent_input.quality_recommendations:
            normalized_recommendation = self._recommendation_from_any(
                recommendation,
                default_source="data_quality_agent",
            )
            if normalized_recommendation is not None:
                recommendations.append(normalized_recommendation)

        if (
            agent_input.is_chart_recommended is True
            and agent_input.chart_generation_status == "chart_not_requested"
        ):
            chart_type = (
                agent_input.recommended_chart_type
                or agent_input.selected_chart_type
                or "chart"
            )

            recommendations.append(
                AnswerRecommendation(
                    recommendation_type="chart_recommended",
                    priority=AnswerRecommendationPriority.LOW,
                    message=(
                        f"A {chart_type} may help visualize this result, but "
                        "no chart was generated because the user did not request one."
                    ),
                    source="chart_agent",
                    metadata={
                        "recommended_chart_type": chart_type,
                    },
                )
            )

        return recommendations

    @staticmethod
    def _chart_unavailable_warning(
        agent_input: AnswerFormatterAgentInput,
    ) -> AnswerWarning | None:
        chart_status = AnswerFormatterAgent._normalize_status(
            agent_input.chart_generation_status
        )

        if chart_status not in {
            "chart_blocked",
            "chart_unavailable",
            "chart_failed",
        }:
            return None

        message = (
            agent_input.chart_error_message
            or agent_input.chart_blocking_reason
            or "Chart generation did not complete."
        )

        severity = (
            AnswerWarningSeverity.CRITICAL
            if chart_status in {"chart_blocked", "chart_failed"}
            else AnswerWarningSeverity.WARNING
        )

        return AnswerWarning(
            warning_type=chart_status,
            severity=severity,
            message=message,
            source="chart_agent",
            recommendation=agent_input.chart_blocking_reason,
            metadata={
                "chart_error_type": agent_input.chart_error_type,
                "requested_chart_type": agent_input.requested_chart_type,
                "selected_chart_type": agent_input.selected_chart_type,
                "recommended_chart_type": agent_input.recommended_chart_type,
            },
        )

    @staticmethod
    def _warning_from_any(
        warning: Any,
        *,
        default_source: str,
    ) -> AnswerWarning | None:
        warning_dict = AnswerFormatterAgent._to_dict(warning)
        if warning_dict is None:
            return None

        warning_type = warning_dict.get("warning_type") or "warning"
        severity = AnswerFormatterAgent._normalize_severity(
            warning_dict.get("severity")
        )
        message = warning_dict.get("message") or warning_type
        source = warning_dict.get("source") or default_source

        metadata = {
            key: value
            for key, value in warning_dict.items()
            if key not in {
                "warning_type",
                "severity",
                "message",
                "source",
                "recommendation",
            }
        }

        metadata.update(warning_dict.get("metadata") or {})

        return AnswerWarning(
            warning_type=str(warning_type),
            severity=severity,
            message=str(message),
            source=str(source),
            recommendation=warning_dict.get("recommendation"),
            metadata=metadata,
        )

    @staticmethod
    def _recommendation_from_any(
        recommendation: Any,
        *,
        default_source: str,
    ) -> AnswerRecommendation | None:
        recommendation_dict = AnswerFormatterAgent._to_dict(recommendation)
        if recommendation_dict is None:
            return None

        recommendation_type = (
            recommendation_dict.get("recommendation_type")
            or "recommendation"
        )
        priority = AnswerFormatterAgent._normalize_priority(
            recommendation_dict.get("priority")
        )
        message = recommendation_dict.get("message") or recommendation_type
        source = recommendation_dict.get("source") or default_source

        metadata = {
            key: value
            for key, value in recommendation_dict.items()
            if key not in {
                "recommendation_type",
                "priority",
                "message",
                "source",
            }
        }

        metadata.update(recommendation_dict.get("metadata") or {})

        return AnswerRecommendation(
            recommendation_type=str(recommendation_type),
            priority=priority,
            message=str(message),
            source=str(source),
            metadata=metadata,
        )

    @staticmethod
    def _to_dict(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value

        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")

        return None

    @staticmethod
    def _normalize_severity(value: Any) -> AnswerWarningSeverity:
        normalized = AnswerFormatterAgent._normalize_status(value)

        if normalized == "critical":
            return AnswerWarningSeverity.CRITICAL

        if normalized == "info":
            return AnswerWarningSeverity.INFO

        return AnswerWarningSeverity.WARNING

    @staticmethod
    def _normalize_priority(value: Any) -> AnswerRecommendationPriority:
        normalized = AnswerFormatterAgent._normalize_status(value)

        if normalized == "high":
            return AnswerRecommendationPriority.HIGH

        if normalized == "medium":
            return AnswerRecommendationPriority.MEDIUM

        return AnswerRecommendationPriority.LOW

    @staticmethod
    def _normalize_status(status: Any) -> str | None:
        if status is None:
            return None

        if isinstance(status, Enum):
            status_value = status.value
        else:
            status_value = str(status)

        normalized_status = status_value.strip().lower()

        return normalized_status or None

    @staticmethod
    def _technical_details(
        agent_input: AnswerFormatterAgentInput,
    ) -> dict[str, Any]:
        return {
            "request_id": agent_input.request_id,
            "routing": {
                "primary_intent": agent_input.primary_intent,
                "required_capabilities": agent_input.required_capabilities,
                "confidence": agent_input.routing_confidence,
                "reason": agent_input.routing_reason,
                "source": agent_input.routing_source,
                "needs_clarification": agent_input.needs_clarification,
                "is_routable": agent_input.is_routable,
                "blocking_reason": agent_input.routing_blocking_reason,
                "unsupported_reason": agent_input.unsupported_reason,
            },
            "sql_generation": {
                "success": agent_input.sql_generation_success,
                "sql_present": bool(agent_input.sql),
                "error_type": agent_input.sql_generation_error_type,
                "error_message": agent_input.sql_generation_error_message,
            },
            "validation": {
                "success": agent_input.validation_success,
                "validation_status": agent_input.validation_status,
                "is_valid": agent_input.is_valid,
                "is_safe_to_execute": agent_input.is_safe_to_execute,
                "error_type": agent_input.validation_error_type,
                "error_message": agent_input.validation_error_message,
                "blocking_reason": agent_input.validation_blocking_reason,
            },
            "execution": {
                "success": agent_input.execution_success,
                "execution_status": agent_input.execution_status,
                "executed": agent_input.executed,
                "row_count": agent_input.row_count,
                "execution_time_ms": agent_input.execution_time_ms,
                "error_type": agent_input.execution_error_type,
                "error_message": agent_input.execution_error_message,
                "blocking_reason": agent_input.execution_blocking_reason,
            },
            "data_quality": {
                "success": agent_input.data_quality_success,
                "quality_status": agent_input.quality_status,
                "is_result_usable": agent_input.is_result_usable,
                "is_result_empty": agent_input.is_result_empty,
                "is_result_too_large": agent_input.is_result_too_large,
                "has_null_warnings": agent_input.has_null_warnings,
                "has_duplicate_warnings": agent_input.has_duplicate_warnings,
                "has_visualization_warnings": (
                    agent_input.has_visualization_warnings
                ),
                "error_type": agent_input.quality_error_type,
                "error_message": agent_input.quality_error_message,
                "blocking_reason": agent_input.quality_blocking_reason,
            },
            "chart": {
                "success": agent_input.chart_success,
                "chart_generation_status": agent_input.chart_generation_status,
                "chart_generation_enabled": agent_input.chart_generation_enabled,
                "chart_type": agent_input.chart_type,
                "selected_chart_type": agent_input.selected_chart_type,
                "requested_chart_type": agent_input.requested_chart_type,
                "recommended_chart_type": agent_input.recommended_chart_type,
                "is_chart_available": agent_input.is_chart_available,
                "is_chart_recommended": agent_input.is_chart_recommended,
                "chart_payload_present": agent_input.chart_payload is not None,
                "error_type": agent_input.chart_error_type,
                "error_message": agent_input.chart_error_message,
                "blocking_reason": agent_input.chart_blocking_reason,
            },
        }

    def _base_metadata(
        self,
        *,
        agent_input: AnswerFormatterAgentInput,
        start_time: float,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            **agent_input.metadata,
            "request_id": agent_input.request_id,
            "agent": "AnswerFormatterAgent",
            "formatter_type": "deterministic_template_formatter",
            "llm_used": False,
            "answer_formatter_execution_time_ms": self._elapsed_ms(start_time),
            **(extra_metadata or {}),
        }

    @staticmethod
    def _elapsed_ms(start_time: float) -> float:
        return round((time.perf_counter() - start_time) * 1000, 3)