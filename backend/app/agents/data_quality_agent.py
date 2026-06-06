# backend/app/agents/data_quality_agent.py

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


SchemaContextBuilderCallable = Callable[[str], dict[str, Any] | None]
DataQualityEvaluatorCallable = Callable[..., dict[str, Any]]


class DataQualityStatus(str, Enum):
    PASSED = "quality_passed"
    WARNING = "quality_warning"
    FAILED = "quality_failed"
    NOT_EVALUATED = "quality_not_evaluated"


class DataQualityErrorType(str, Enum):
    SCHEMA_CONTEXT_NOT_FOUND = "schema_context_not_found"
    INVALID_SCHEMA_CONTEXT = "invalid_schema_context"
    EXECUTION_NOT_SUCCESSFUL = "execution_not_successful"
    INVALID_RESULT_PAYLOAD = "invalid_result_payload"
    DATA_QUALITY_SERVICE_UNAVAILABLE = "data_quality_service_unavailable"
    INVALID_QUALITY_RESPONSE = "invalid_quality_response"
    UNEXPECTED_QUALITY_ERROR = "unexpected_quality_error"


class DataQualityWarningSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class DataQualityRecommendationPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DataQualityWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warning_type: str
    severity: DataQualityWarningSeverity
    message: str

    column: str | None = None
    recommendation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataQualityRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_type: str
    priority: DataQualityRecommendationPriority
    message: str

    column: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataQualityAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)

    sql: str | None = None
    results: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int | None = Field(default=None, ge=0)

    success: bool | None = None
    execution_success: bool | None = None
    executed: bool | None = None
    execution_status: str | None = None
    execution_time_ms: float | None = Field(default=None, ge=0)

    error_type: str | None = None
    error_message: str | None = None
    blocking_reason: str | None = None

    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataQualityAgentOutput(BaseModel):
    success: bool

    dataset_id: str
    question: str
    sql: str | None = None

    quality_status: DataQualityStatus

    is_result_usable: bool
    is_result_empty: bool
    is_result_too_large: bool

    has_null_warnings: bool
    has_duplicate_warnings: bool
    has_visualization_warnings: bool

    row_count: int
    execution_time_ms: float | None = None

    warnings: list[DataQualityWarning] = Field(default_factory=list)
    recommendations: list[DataQualityRecommendation] = Field(default_factory=list)

    error_type: DataQualityErrorType | None = None
    error_message: str | None = None
    blocking_reason: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class DataQualityAgent:
    """
    Production-style Data Quality Agent wrapper.

    Responsibilities:
    - Accept structured query execution output.
    - Refuse evaluation when upstream execution failed or was blocked.
    - Resolve trusted dataset metadata internally from dataset_id.
    - Call the deterministic data-quality evaluator service.
    - Return structured quality status, warnings, recommendations, and flags.

    Non-responsibilities:
    - SQL generation.
    - SQL validation.
    - SQL execution.
    - Data cleaning or mutation.
    - Chart payload creation.
    - Final natural-language answer formatting.
    - LangGraph orchestration.
    """

    def __init__(
        self,
        schema_context_builder: SchemaContextBuilderCallable | None = None,
        data_quality_evaluator: DataQualityEvaluatorCallable | None = None,
    ) -> None:
        self.schema_context_builder = schema_context_builder
        self.data_quality_evaluator = data_quality_evaluator

    def evaluate(
        self,
        agent_input: DataQualityAgentInput,
    ) -> DataQualityAgentOutput:
        start_time = time.perf_counter()

        normalized_execution_status = self._normalize_status(
            agent_input.execution_status
        )
        row_count = self._resolve_row_count(agent_input)

        if self._upstream_execution_not_successful(
            agent_input=agent_input,
            normalized_execution_status=normalized_execution_status,
        ):
            return self._not_evaluated(
                agent_input=agent_input,
                row_count=row_count,
                start_time=start_time,
                normalized_execution_status=normalized_execution_status,
            )

        result_payload_error = self._validate_result_payload(
            agent_input=agent_input,
            row_count=row_count,
        )

        if result_payload_error is not None:
            return self._technical_failure(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                quality_status=DataQualityStatus.FAILED,
                error_type=DataQualityErrorType.INVALID_RESULT_PAYLOAD,
                error_message=result_payload_error,
                blocking_reason=(
                    "Data quality evaluation could not continue because the "
                    "query result payload is invalid."
                ),
                warning_type="invalid_result_payload",
                warning_message=result_payload_error,
                normalized_execution_status=normalized_execution_status,
            )

        try:
            schema_context_builder = self._resolve_schema_context_builder()
            schema_context = schema_context_builder(agent_input.dataset_id)

        except Exception as exc:
            logger.exception("Schema context builder could not be loaded.")

            return self._technical_failure(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                quality_status=DataQualityStatus.FAILED,
                error_type=DataQualityErrorType.DATA_QUALITY_SERVICE_UNAVAILABLE,
                error_message=str(exc),
                blocking_reason=(
                    "Trusted schema context could not be resolved because the "
                    "schema context builder is unavailable."
                ),
                warning_type="dataset_metadata_unavailable",
                warning_message=(
                    "Trusted dataset metadata could not be loaded for data "
                    "quality evaluation."
                ),
                normalized_execution_status=normalized_execution_status,
                extra_metadata={
                    "exception_type": type(exc).__name__,
                },
            )

        if schema_context is None:
            return self._technical_failure(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                quality_status=DataQualityStatus.FAILED,
                error_type=DataQualityErrorType.SCHEMA_CONTEXT_NOT_FOUND,
                error_message=(
                    f"No trusted schema context found for dataset_id "
                    f"{agent_input.dataset_id!r}."
                ),
                blocking_reason=(
                    "Data quality evaluation requires trusted dataset metadata."
                ),
                warning_type="dataset_metadata_unavailable",
                warning_message=(
                    "Trusted dataset metadata was not found for this dataset."
                ),
                normalized_execution_status=normalized_execution_status,
            )

        schema_context_error = self._validate_schema_context(schema_context)

        if schema_context_error is not None:
            return self._technical_failure(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                quality_status=DataQualityStatus.FAILED,
                error_type=DataQualityErrorType.INVALID_SCHEMA_CONTEXT,
                error_message=schema_context_error,
                blocking_reason=(
                    "Trusted schema context is present but invalid."
                ),
                warning_type="invalid_schema_context",
                warning_message=schema_context_error,
                normalized_execution_status=normalized_execution_status,
            )

        try:
            data_quality_evaluator = self._resolve_data_quality_evaluator()

            evaluation_result = data_quality_evaluator(
                dataset_id=agent_input.dataset_id,
                question=agent_input.question,
                sql=agent_input.sql,
                results=agent_input.results,
                row_count=row_count,
                schema_context=schema_context,
                execution_time_ms=agent_input.execution_time_ms,
            )

        except Exception as exc:
            logger.exception("Unexpected data quality evaluation error.")

            return self._technical_failure(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                quality_status=DataQualityStatus.FAILED,
                error_type=DataQualityErrorType.UNEXPECTED_QUALITY_ERROR,
                error_message=str(exc),
                blocking_reason=(
                    "Data quality evaluation failed due to an unexpected "
                    "internal error."
                ),
                warning_type="unexpected_quality_error",
                warning_message=(
                    "The data quality evaluator failed unexpectedly."
                ),
                normalized_execution_status=normalized_execution_status,
                extra_metadata={
                    "exception_type": type(exc).__name__,
                },
            )

        response_error = self._validate_evaluation_result(evaluation_result)

        if response_error is not None:
            return self._technical_failure(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                quality_status=DataQualityStatus.FAILED,
                error_type=DataQualityErrorType.INVALID_QUALITY_RESPONSE,
                error_message=response_error,
                blocking_reason=(
                    "Data quality evaluator returned an invalid response."
                ),
                warning_type="invalid_quality_response",
                warning_message=response_error,
                normalized_execution_status=normalized_execution_status,
            )

        return self._success_from_evaluation_result(
            agent_input=agent_input,
            evaluation_result=evaluation_result,
            start_time=start_time,
            normalized_execution_status=normalized_execution_status,
        )

    def _resolve_schema_context_builder(self) -> SchemaContextBuilderCallable:
        if self.schema_context_builder is not None:
            return self.schema_context_builder

        from app.services.schema_context_builder import build_schema_context

        return build_schema_context

    def _resolve_data_quality_evaluator(self) -> DataQualityEvaluatorCallable:
        if self.data_quality_evaluator is not None:
            return self.data_quality_evaluator

        from app.services.data_quality_evaluator import evaluate_data_quality

        return evaluate_data_quality

    def _not_evaluated(
        self,
        *,
        agent_input: DataQualityAgentInput,
        row_count: int,
        start_time: float,
        normalized_execution_status: str | None,
    ) -> DataQualityAgentOutput:
        warning = DataQualityWarning(
            warning_type="execution_not_successful",
            severity=DataQualityWarningSeverity.CRITICAL,
            message=(
                "Data quality checks were not performed because upstream query "
                "execution did not succeed."
            ),
            recommendation=(
                "Fix the upstream SQL validation or execution failure before "
                "running data quality evaluation."
            ),
            metadata={
                "upstream_success": agent_input.success,
                "upstream_execution_success": agent_input.execution_success,
                "upstream_executed": agent_input.executed,
                "upstream_execution_status": normalized_execution_status,
                "upstream_error_type": agent_input.error_type,
                "upstream_error_message": agent_input.error_message,
                "upstream_blocking_reason": agent_input.blocking_reason,
            },
        )

        return DataQualityAgentOutput(
            success=False,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            sql=agent_input.sql,
            quality_status=DataQualityStatus.NOT_EVALUATED,
            is_result_usable=False,
            is_result_empty=row_count == 0,
            is_result_too_large=False,
            has_null_warnings=False,
            has_duplicate_warnings=False,
            has_visualization_warnings=False,
            row_count=row_count,
            execution_time_ms=agent_input.execution_time_ms,
            warnings=[warning],
            recommendations=[],
            error_type=DataQualityErrorType.EXECUTION_NOT_SUCCESSFUL,
            error_message=(
                "Upstream query execution did not succeed, so data quality was "
                "not evaluated."
            ),
            blocking_reason=(
                "Data quality evaluation requires successful query execution."
            ),
            metadata=self._base_metadata(
                agent_input=agent_input,
                start_time=start_time,
                normalized_execution_status=normalized_execution_status,
                extra_metadata={
                    "quality_evaluated": False,
                    "schema_context_resolved": False,
                },
            ),
        )

    def _technical_failure(
        self,
        *,
        agent_input: DataQualityAgentInput,
        start_time: float,
        row_count: int,
        quality_status: DataQualityStatus,
        error_type: DataQualityErrorType,
        error_message: str,
        blocking_reason: str,
        warning_type: str,
        warning_message: str,
        normalized_execution_status: str | None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> DataQualityAgentOutput:
        warning = DataQualityWarning(
            warning_type=warning_type,
            severity=DataQualityWarningSeverity.CRITICAL,
            message=warning_message,
            recommendation=blocking_reason,
            metadata={
                "error_type": error_type.value,
            },
        )

        return DataQualityAgentOutput(
            success=False,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            sql=agent_input.sql,
            quality_status=quality_status,
            is_result_usable=False,
            is_result_empty=row_count == 0,
            is_result_too_large=False,
            has_null_warnings=False,
            has_duplicate_warnings=False,
            has_visualization_warnings=False,
            row_count=row_count,
            execution_time_ms=agent_input.execution_time_ms,
            warnings=[warning],
            recommendations=[],
            error_type=error_type,
            error_message=error_message,
            blocking_reason=blocking_reason,
            metadata=self._base_metadata(
                agent_input=agent_input,
                start_time=start_time,
                normalized_execution_status=normalized_execution_status,
                extra_metadata={
                    "quality_evaluated": False,
                    **(extra_metadata or {}),
                },
            ),
        )

    def _success_from_evaluation_result(
        self,
        *,
        agent_input: DataQualityAgentInput,
        evaluation_result: dict[str, Any],
        start_time: float,
        normalized_execution_status: str | None,
    ) -> DataQualityAgentOutput:
        quality_status = DataQualityStatus(
            evaluation_result["quality_status"]
        )

        warnings = [
            DataQualityWarning(**warning)
            for warning in evaluation_result["warnings"]
        ]
        recommendations = [
            DataQualityRecommendation(**recommendation)
            for recommendation in evaluation_result["recommendations"]
        ]

        return DataQualityAgentOutput(
            success=True,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            sql=agent_input.sql,
            quality_status=quality_status,
            is_result_usable=evaluation_result["is_result_usable"],
            is_result_empty=evaluation_result["is_result_empty"],
            is_result_too_large=evaluation_result["is_result_too_large"],
            has_null_warnings=evaluation_result["has_null_warnings"],
            has_duplicate_warnings=evaluation_result["has_duplicate_warnings"],
            has_visualization_warnings=(
                evaluation_result["has_visualization_warnings"]
            ),
            row_count=evaluation_result["row_count"],
            execution_time_ms=agent_input.execution_time_ms,
            warnings=warnings,
            recommendations=recommendations,
            error_type=None,
            error_message=None,
            blocking_reason=None,
            metadata=self._base_metadata(
                agent_input=agent_input,
                start_time=start_time,
                normalized_execution_status=normalized_execution_status,
                extra_metadata={
                    "quality_evaluated": True,
                    "schema_context_resolved": True,
                    "quality_metadata": evaluation_result.get("metadata", {}),
                },
            ),
        )

    @staticmethod
    def _validate_result_payload(
        *,
        agent_input: DataQualityAgentInput,
        row_count: int,
    ) -> str | None:
        if not isinstance(agent_input.results, list):
            return "results must be a list."

        for row in agent_input.results:
            if not isinstance(row, dict):
                return "results must contain dictionaries."

        if agent_input.row_count is not None and row_count != len(agent_input.results):
            return (
                "row_count does not match the number of result rows. "
                f"row_count={row_count}, result_rows={len(agent_input.results)}."
            )

        return None

    @staticmethod
    def _validate_schema_context(
        schema_context: dict[str, Any],
    ) -> str | None:
        if not isinstance(schema_context, dict):
            return "schema_context must be a dictionary."

        required_keys = [
            "dataset_id",
            "table_name",
            "row_count",
            "column_count",
            "schema_profile",
        ]

        missing_keys = [
            key
            for key in required_keys
            if key not in schema_context
        ]

        if missing_keys:
            return f"schema_context is missing key(s): {missing_keys}."

        schema_profile = schema_context["schema_profile"]

        if not isinstance(schema_profile, dict):
            return "schema_context.schema_profile must be a dictionary."

        columns = schema_profile.get("columns")

        if not isinstance(columns, list):
            return "schema_profile.columns must be a list."

        return None

    @staticmethod
    def _validate_evaluation_result(
        evaluation_result: Any,
    ) -> str | None:
        if not isinstance(evaluation_result, dict):
            return "Data quality evaluator response must be a dictionary."

        required_keys = [
            "quality_status",
            "is_result_usable",
            "is_result_empty",
            "is_result_too_large",
            "has_null_warnings",
            "has_duplicate_warnings",
            "has_visualization_warnings",
            "row_count",
            "warnings",
            "recommendations",
            "metadata",
        ]

        missing_keys = [
            key
            for key in required_keys
            if key not in evaluation_result
        ]

        if missing_keys:
            return (
                "Data quality evaluator response is missing key(s): "
                f"{missing_keys}."
            )

        try:
            DataQualityStatus(evaluation_result["quality_status"])
        except ValueError:
            return (
                "Data quality evaluator response contains invalid "
                "quality_status."
            )

        if not isinstance(evaluation_result["warnings"], list):
            return "Data quality evaluator response warnings must be a list."

        if not isinstance(evaluation_result["recommendations"], list):
            return (
                "Data quality evaluator response recommendations must be a list."
            )

        if not isinstance(evaluation_result["metadata"], dict):
            return "Data quality evaluator response metadata must be a dictionary."

        return None

    @staticmethod
    def _resolve_row_count(
        agent_input: DataQualityAgentInput,
    ) -> int:
        if agent_input.row_count is not None:
            return agent_input.row_count

        return len(agent_input.results)

    @staticmethod
    def _upstream_execution_not_successful(
        *,
        agent_input: DataQualityAgentInput,
        normalized_execution_status: str | None,
    ) -> bool:
        if agent_input.success is False:
            return True

        if agent_input.execution_success is False:
            return True

        if agent_input.executed is False:
            return True

        if (
            normalized_execution_status is not None
            and normalized_execution_status != "execution_succeeded"
        ):
            return True

        return False

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

    def _base_metadata(
        self,
        *,
        agent_input: DataQualityAgentInput,
        start_time: float,
        normalized_execution_status: str | None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            **agent_input.metadata,
            "request_id": agent_input.request_id,
            "agent": "DataQualityAgent",
            "service": "evaluate_data_quality",
            "schema_context_source": "build_schema_context",
            "upstream_success": agent_input.success,
            "upstream_execution_success": agent_input.execution_success,
            "upstream_executed": agent_input.executed,
            "upstream_execution_status": normalized_execution_status,
            "upstream_error_type": agent_input.error_type,
            "quality_agent_execution_time_ms": self._elapsed_ms(start_time),
            **(extra_metadata or {}),
        }

    @staticmethod
    def _elapsed_ms(start_time: float) -> float:
        return round((time.perf_counter() - start_time) * 1000, 3)