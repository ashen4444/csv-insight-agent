# backend/app/agents/chart_agent.py

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


VisualizationIntentDetectorCallable = Callable[[str], dict[str, Any]]
ResultAnalyzerCallable = Callable[..., dict[str, Any]]
ChartSelectorCallable = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
ChartPayloadBuilderCallable = Callable[
    [list[dict[str, Any]], dict[str, Any], dict[str, Any]],
    dict[str, Any] | None,
]
ChartValidatorCallable = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any] | None],
    dict[str, Any],
]


class ChartGenerationStatus(str, Enum):
    GENERATED = "chart_generated"
    GENERATED_WITH_WARNING = "chart_generated_with_warning"
    NOT_REQUESTED = "chart_not_requested"
    BLOCKED = "chart_blocked"
    UNAVAILABLE = "chart_unavailable"
    FAILED = "chart_failed"


class ChartAgentErrorType(str, Enum):
    UPSTREAM_EXECUTION_NOT_SUCCESSFUL = "upstream_execution_not_successful"
    INVALID_RESULT_PAYLOAD = "invalid_result_payload"
    DATA_QUALITY_BLOCKED = "data_quality_blocked"
    RESULT_NOT_VISUALIZABLE = "result_not_visualizable"
    CHART_PAYLOAD_UNAVAILABLE = "chart_payload_unavailable"
    CHART_SERVICE_UNAVAILABLE = "chart_service_unavailable"
    INVALID_SERVICE_RESPONSE = "invalid_service_response"
    UNEXPECTED_CHART_ERROR = "unexpected_chart_error"


class ChartWarningSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ChartWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warning_type: str
    severity: ChartWarningSeverity
    message: str

    source: str = "chart_agent"
    recommendation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChartAgentInput(BaseModel):
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

    data_quality_status: str | None = None
    is_result_usable: bool | None = None
    is_result_empty: bool | None = None
    is_result_too_large: bool | None = None
    has_visualization_warnings: bool | None = None

    quality_warnings: list[Any] = Field(default_factory=list)
    quality_recommendations: list[Any] = Field(default_factory=list)
    quality_metadata: dict[str, Any] = Field(default_factory=dict)

    chart_generation_approved: bool = False
    approved_chart_type: str | None = None

    error_type: str | None = None
    error_message: str | None = None
    blocking_reason: str | None = None

    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChartAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool

    dataset_id: str
    question: str
    sql: str | None = None

    chart_generation_status: ChartGenerationStatus
    chart_generation_enabled: bool

    chart_type: str | None = None
    selected_chart_type: str | None = None
    requested_chart_type: str | None = None
    recommended_chart_type: str | None = None
    chart_source: str | None = None

    chart_payload: dict[str, Any] | None = None

    chart_warning: ChartWarning | None = None
    chart_warnings: list[ChartWarning] = Field(default_factory=list)

    is_chart_available: bool
    is_chart_recommended: bool

    visualization_intent: dict[str, Any] = Field(default_factory=dict)
    result_analysis: dict[str, Any] = Field(default_factory=dict)
    chart_selection: dict[str, Any] = Field(default_factory=dict)

    error_type: ChartAgentErrorType | None = None
    error_message: str | None = None
    blocking_reason: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ChartAgent:
    """
    Production-style Chart Agent wrapper.

    Responsibilities:
    - Accept structured query execution and data-quality output.
    - Detect whether chart generation was requested or approved.
    - Analyze executed query results.
    - Select a chart using the existing chart selector service.
    - Build a frontend-friendly chart payload using the existing payload builder.
    - Validate chart selection and expose warnings for downstream agents.

    Non-responsibilities:
    - SQL generation.
    - SQL validation.
    - SQL execution.
    - Data cleaning or mutation.
    - Final natural-language answer formatting.
    - LangGraph orchestration.
    - LLM calls.
    """

    def __init__(
        self,
        visualization_intent_detector: VisualizationIntentDetectorCallable | None = None,
        result_analyzer: ResultAnalyzerCallable | None = None,
        chart_selector: ChartSelectorCallable | None = None,
        chart_payload_builder: ChartPayloadBuilderCallable | None = None,
        chart_validator: ChartValidatorCallable | None = None,
    ) -> None:
        self.visualization_intent_detector = visualization_intent_detector
        self.result_analyzer = result_analyzer
        self.chart_selector = chart_selector
        self.chart_payload_builder = chart_payload_builder
        self.chart_validator = chart_validator

    def generate(
        self,
        agent_input: ChartAgentInput,
    ) -> ChartAgentOutput:
        return self.build_chart(agent_input)

    def build_chart(
        self,
        agent_input: ChartAgentInput,
    ) -> ChartAgentOutput:
        start_time = time.perf_counter()

        normalized_execution_status = self._normalize_status(
            agent_input.execution_status
        )
        row_count = self._resolve_row_count(agent_input)

        if self._upstream_execution_not_successful(
            agent_input=agent_input,
            normalized_execution_status=normalized_execution_status,
        ):
            return self._blocked_output(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                normalized_execution_status=normalized_execution_status,
                error_type=ChartAgentErrorType.UPSTREAM_EXECUTION_NOT_SUCCESSFUL,
                error_message=(
                    "Chart generation was skipped because upstream query "
                    "execution did not succeed."
                ),
                blocking_reason=(
                    "Chart generation requires successful query execution."
                ),
                warning_type="execution_not_successful",
            )

        result_payload_error = self._validate_result_payload(
            agent_input=agent_input,
            row_count=row_count,
        )

        if result_payload_error is not None:
            return self._blocked_output(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                normalized_execution_status=normalized_execution_status,
                error_type=ChartAgentErrorType.INVALID_RESULT_PAYLOAD,
                error_message=result_payload_error,
                blocking_reason=(
                    "Chart generation requires a valid executed result payload."
                ),
                warning_type="invalid_result_payload",
            )

        data_quality_blocking_reason = self._data_quality_blocking_reason(
            agent_input
        )

        if data_quality_blocking_reason is not None:
            return self._blocked_output(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                normalized_execution_status=normalized_execution_status,
                error_type=ChartAgentErrorType.DATA_QUALITY_BLOCKED,
                error_message=data_quality_blocking_reason,
                blocking_reason=data_quality_blocking_reason,
                warning_type="data_quality_blocked",
            )

        try:
            visualization_intent = self._resolve_visualization_intent_detector()(
                agent_input.question
            )

            intent_error = self._validate_visualization_intent(
                visualization_intent
            )
            if intent_error is not None:
                return self._failed_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    row_count=row_count,
                    normalized_execution_status=normalized_execution_status,
                    error_type=ChartAgentErrorType.INVALID_SERVICE_RESPONSE,
                    error_message=intent_error,
                    blocking_reason=(
                        "Chart Agent could not continue because visualization "
                        "intent detection returned an invalid response."
                    ),
                )

            visualization_intent = self._apply_chart_approval(
                agent_input=agent_input,
                visualization_intent=visualization_intent,
            )

            result_analysis = self._resolve_result_analyzer()(
                agent_input.results,
                question=agent_input.question,
                visualization_intent=visualization_intent,
            )

            analysis_error = self._validate_result_analysis(result_analysis)
            if analysis_error is not None:
                return self._failed_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    row_count=row_count,
                    normalized_execution_status=normalized_execution_status,
                    error_type=ChartAgentErrorType.INVALID_SERVICE_RESPONSE,
                    error_message=analysis_error,
                    blocking_reason=(
                        "Chart Agent could not continue because result analysis "
                        "returned an invalid response."
                    ),
                    visualization_intent=visualization_intent,
                )

            chart_selection = self._resolve_chart_selector()(
                result_analysis,
                visualization_intent,
            )

            selection_error = self._validate_chart_selection(chart_selection)
            if selection_error is not None:
                return self._failed_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    row_count=row_count,
                    normalized_execution_status=normalized_execution_status,
                    error_type=ChartAgentErrorType.INVALID_SERVICE_RESPONSE,
                    error_message=selection_error,
                    blocking_reason=(
                        "Chart Agent could not continue because chart selection "
                        "returned an invalid response."
                    ),
                    visualization_intent=visualization_intent,
                    result_analysis=result_analysis,
                )

            is_chart_recommended = self._is_chart_recommended(result_analysis)
            non_blocking_quality_warnings = (
                self._non_blocking_quality_chart_warnings(agent_input)
            )

            if not visualization_intent.get("visualization_requested", False):
                return self._not_requested_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    row_count=row_count,
                    normalized_execution_status=normalized_execution_status,
                    visualization_intent=visualization_intent,
                    result_analysis=result_analysis,
                    chart_selection=chart_selection,
                    is_chart_recommended=is_chart_recommended,
                    chart_warnings=non_blocking_quality_warnings,
                )

            if chart_selection.get("chart_generation_enabled") is not True:
                return self._unavailable_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    row_count=row_count,
                    normalized_execution_status=normalized_execution_status,
                    visualization_intent=visualization_intent,
                    result_analysis=result_analysis,
                    chart_selection=chart_selection,
                    is_chart_recommended=is_chart_recommended,
                    chart_warnings=non_blocking_quality_warnings,
                    error_type=ChartAgentErrorType.RESULT_NOT_VISUALIZABLE,
                    error_message=(
                        "Chart generation was requested, but the query result "
                        "is not suitable for a chart."
                    ),
                    blocking_reason=(
                        "The analyzed query result does not contain a supported "
                        "chart shape."
                    ),
                )

            chart_payload = self._resolve_chart_payload_builder()(
                agent_input.results,
                result_analysis,
                chart_selection,
            )

            chart_validation = self._resolve_chart_validator()(
                result_analysis,
                chart_selection,
                chart_payload,
            )

            validation_error = self._validate_chart_validation(chart_validation)
            if validation_error is not None:
                return self._failed_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    row_count=row_count,
                    normalized_execution_status=normalized_execution_status,
                    error_type=ChartAgentErrorType.INVALID_SERVICE_RESPONSE,
                    error_message=validation_error,
                    blocking_reason=(
                        "Chart Agent could not continue because chart validation "
                        "returned an invalid response."
                    ),
                    visualization_intent=visualization_intent,
                    result_analysis=result_analysis,
                    chart_selection=chart_selection,
                )

            chart_warnings = [
                *non_blocking_quality_warnings,
                *self._warnings_from_chart_validation(chart_validation),
            ]

            if chart_payload is None:
                return self._unavailable_output(
                    agent_input=agent_input,
                    start_time=start_time,
                    row_count=row_count,
                    normalized_execution_status=normalized_execution_status,
                    visualization_intent=visualization_intent,
                    result_analysis=result_analysis,
                    chart_selection=chart_selection,
                    is_chart_recommended=is_chart_recommended,
                    chart_warnings=chart_warnings,
                    error_type=ChartAgentErrorType.CHART_PAYLOAD_UNAVAILABLE,
                    error_message=(
                        "Chart generation was requested, but a chart payload "
                        "could not be built from the result."
                    ),
                    blocking_reason=(
                        "The selected chart type is unsupported by the current "
                        "payload builder or the result does not contain usable "
                        "chart axes."
                    ),
                )

            status = (
                ChartGenerationStatus.GENERATED_WITH_WARNING
                if chart_warnings
                else ChartGenerationStatus.GENERATED
            )

            return ChartAgentOutput(
                success=True,
                dataset_id=agent_input.dataset_id,
                question=agent_input.question,
                sql=agent_input.sql,
                chart_generation_status=status,
                chart_generation_enabled=True,
                chart_type=chart_payload.get("chart_type"),
                selected_chart_type=chart_selection.get("final_chart_type"),
                requested_chart_type=visualization_intent.get(
                    "requested_chart_type"
                ),
                recommended_chart_type=result_analysis.get(
                    "recommended_visualization"
                ),
                chart_source=chart_selection.get("chart_source"),
                chart_payload=chart_payload,
                chart_warning=self._first_warning(chart_warnings),
                chart_warnings=chart_warnings,
                is_chart_available=True,
                is_chart_recommended=is_chart_recommended,
                visualization_intent=visualization_intent,
                result_analysis=result_analysis,
                chart_selection=chart_selection,
                error_type=None,
                error_message=None,
                blocking_reason=None,
                metadata=self._base_metadata(
                    agent_input=agent_input,
                    start_time=start_time,
                    row_count=row_count,
                    normalized_execution_status=normalized_execution_status,
                    extra_metadata={
                        "chart_generated": True,
                        "chart_warning_count": len(chart_warnings),
                    },
                ),
            )

        except ImportError as exc:
            logger.exception("Chart service could not be imported.")

            return self._failed_output(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                normalized_execution_status=normalized_execution_status,
                error_type=ChartAgentErrorType.CHART_SERVICE_UNAVAILABLE,
                error_message=str(exc),
                blocking_reason=(
                    "Chart generation could not continue because a required "
                    "chart service is unavailable."
                ),
                extra_metadata={
                    "exception_type": type(exc).__name__,
                },
            )

        except Exception as exc:
            logger.exception("Unexpected Chart Agent error.")

            return self._failed_output(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                normalized_execution_status=normalized_execution_status,
                error_type=ChartAgentErrorType.UNEXPECTED_CHART_ERROR,
                error_message=str(exc),
                blocking_reason=(
                    "Chart generation failed because of an unexpected internal "
                    "error."
                ),
                extra_metadata={
                    "exception_type": type(exc).__name__,
                },
            )

    def _resolve_visualization_intent_detector(
        self,
    ) -> VisualizationIntentDetectorCallable:
        if self.visualization_intent_detector is not None:
            return self.visualization_intent_detector

        from app.services.visualization_intent_detector import (
            detect_visualization_intent,
        )

        return detect_visualization_intent

    def _resolve_result_analyzer(self) -> ResultAnalyzerCallable:
        if self.result_analyzer is not None:
            return self.result_analyzer

        from app.services.result_analyzer import analyze_results

        return analyze_results

    def _resolve_chart_selector(self) -> ChartSelectorCallable:
        if self.chart_selector is not None:
            return self.chart_selector

        from app.services.chart_selector import select_chart

        return select_chart

    def _resolve_chart_payload_builder(self) -> ChartPayloadBuilderCallable:
        if self.chart_payload_builder is not None:
            return self.chart_payload_builder

        from app.services.chart_payload_builder import build_chart_payload

        return build_chart_payload

    def _resolve_chart_validator(self) -> ChartValidatorCallable:
        if self.chart_validator is not None:
            return self.chart_validator

        from app.services.chart_validator import validate_chart_selection

        return validate_chart_selection

    def _blocked_output(
        self,
        *,
        agent_input: ChartAgentInput,
        start_time: float,
        row_count: int,
        normalized_execution_status: str | None,
        error_type: ChartAgentErrorType,
        error_message: str,
        blocking_reason: str,
        warning_type: str,
    ) -> ChartAgentOutput:
        warning = ChartWarning(
            warning_type=warning_type,
            severity=ChartWarningSeverity.CRITICAL,
            message=error_message,
            recommendation=blocking_reason,
            metadata={
                "error_type": error_type.value,
            },
        )

        return ChartAgentOutput(
            success=False,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            sql=agent_input.sql,
            chart_generation_status=ChartGenerationStatus.BLOCKED,
            chart_generation_enabled=False,
            chart_type=None,
            selected_chart_type=None,
            requested_chart_type=None,
            recommended_chart_type=None,
            chart_source=None,
            chart_payload=None,
            chart_warning=warning,
            chart_warnings=[warning],
            is_chart_available=False,
            is_chart_recommended=False,
            visualization_intent={},
            result_analysis={},
            chart_selection={},
            error_type=error_type,
            error_message=error_message,
            blocking_reason=blocking_reason,
            metadata=self._base_metadata(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                normalized_execution_status=normalized_execution_status,
                extra_metadata={
                    "chart_generated": False,
                    "chart_blocked": True,
                },
            ),
        )

    def _failed_output(
        self,
        *,
        agent_input: ChartAgentInput,
        start_time: float,
        row_count: int,
        normalized_execution_status: str | None,
        error_type: ChartAgentErrorType,
        error_message: str,
        blocking_reason: str,
        visualization_intent: dict[str, Any] | None = None,
        result_analysis: dict[str, Any] | None = None,
        chart_selection: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> ChartAgentOutput:
        warning = ChartWarning(
            warning_type=error_type.value,
            severity=ChartWarningSeverity.CRITICAL,
            message=error_message,
            recommendation=blocking_reason,
            metadata={
                "error_type": error_type.value,
            },
        )

        return ChartAgentOutput(
            success=False,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            sql=agent_input.sql,
            chart_generation_status=ChartGenerationStatus.FAILED,
            chart_generation_enabled=False,
            chart_type=None,
            selected_chart_type=(
                chart_selection or {}
            ).get("final_chart_type"),
            requested_chart_type=(
                visualization_intent or {}
            ).get("requested_chart_type"),
            recommended_chart_type=(
                result_analysis or {}
            ).get("recommended_visualization"),
            chart_source=(chart_selection or {}).get("chart_source"),
            chart_payload=None,
            chart_warning=warning,
            chart_warnings=[warning],
            is_chart_available=False,
            is_chart_recommended=self._is_chart_recommended(
                result_analysis or {}
            ),
            visualization_intent=visualization_intent or {},
            result_analysis=result_analysis or {},
            chart_selection=chart_selection or {},
            error_type=error_type,
            error_message=error_message,
            blocking_reason=blocking_reason,
            metadata=self._base_metadata(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                normalized_execution_status=normalized_execution_status,
                extra_metadata={
                    "chart_generated": False,
                    "chart_failed": True,
                    **(extra_metadata or {}),
                },
            ),
        )

    def _not_requested_output(
        self,
        *,
        agent_input: ChartAgentInput,
        start_time: float,
        row_count: int,
        normalized_execution_status: str | None,
        visualization_intent: dict[str, Any],
        result_analysis: dict[str, Any],
        chart_selection: dict[str, Any],
        is_chart_recommended: bool,
        chart_warnings: list[ChartWarning],
    ) -> ChartAgentOutput:
        return ChartAgentOutput(
            success=True,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            sql=agent_input.sql,
            chart_generation_status=ChartGenerationStatus.NOT_REQUESTED,
            chart_generation_enabled=False,
            chart_type=None,
            selected_chart_type=None,
            requested_chart_type=visualization_intent.get(
                "requested_chart_type"
            ),
            recommended_chart_type=result_analysis.get(
                "recommended_visualization"
            ),
            chart_source=None,
            chart_payload=None,
            chart_warning=self._first_warning(chart_warnings),
            chart_warnings=chart_warnings,
            is_chart_available=False,
            is_chart_recommended=is_chart_recommended,
            visualization_intent=visualization_intent,
            result_analysis=result_analysis,
            chart_selection=chart_selection,
            error_type=None,
            error_message=None,
            blocking_reason=None,
            metadata=self._base_metadata(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                normalized_execution_status=normalized_execution_status,
                extra_metadata={
                    "chart_generated": False,
                    "chart_not_requested": True,
                },
            ),
        )

    def _unavailable_output(
        self,
        *,
        agent_input: ChartAgentInput,
        start_time: float,
        row_count: int,
        normalized_execution_status: str | None,
        visualization_intent: dict[str, Any],
        result_analysis: dict[str, Any],
        chart_selection: dict[str, Any],
        is_chart_recommended: bool,
        chart_warnings: list[ChartWarning],
        error_type: ChartAgentErrorType,
        error_message: str,
        blocking_reason: str,
    ) -> ChartAgentOutput:
        warning = ChartWarning(
            warning_type=error_type.value,
            severity=ChartWarningSeverity.WARNING,
            message=error_message,
            recommendation=blocking_reason,
            metadata={
                "selected_chart_type": chart_selection.get("final_chart_type"),
                "recommended_chart_type": result_analysis.get(
                    "recommended_visualization"
                ),
            },
        )

        all_warnings = [*chart_warnings, warning]

        return ChartAgentOutput(
            success=False,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            sql=agent_input.sql,
            chart_generation_status=ChartGenerationStatus.UNAVAILABLE,
            chart_generation_enabled=chart_selection.get(
                "chart_generation_enabled",
                False,
            ),
            chart_type=None,
            selected_chart_type=chart_selection.get("final_chart_type"),
            requested_chart_type=visualization_intent.get(
                "requested_chart_type"
            ),
            recommended_chart_type=result_analysis.get(
                "recommended_visualization"
            ),
            chart_source=chart_selection.get("chart_source"),
            chart_payload=None,
            chart_warning=self._first_warning(all_warnings),
            chart_warnings=all_warnings,
            is_chart_available=False,
            is_chart_recommended=is_chart_recommended,
            visualization_intent=visualization_intent,
            result_analysis=result_analysis,
            chart_selection=chart_selection,
            error_type=error_type,
            error_message=error_message,
            blocking_reason=blocking_reason,
            metadata=self._base_metadata(
                agent_input=agent_input,
                start_time=start_time,
                row_count=row_count,
                normalized_execution_status=normalized_execution_status,
                extra_metadata={
                    "chart_generated": False,
                    "chart_unavailable": True,
                },
            ),
        )

    @staticmethod
    def _apply_chart_approval(
        *,
        agent_input: ChartAgentInput,
        visualization_intent: dict[str, Any],
    ) -> dict[str, Any]:
        if not agent_input.chart_generation_approved:
            return visualization_intent

        return {
            **visualization_intent,
            "visualization_requested": True,
            "requested_chart_type": agent_input.approved_chart_type,
            "approval_source": "chart_generation_approved",
        }

    @staticmethod
    def _validate_result_payload(
        *,
        agent_input: ChartAgentInput,
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
    def _validate_visualization_intent(
        visualization_intent: Any,
    ) -> str | None:
        if not isinstance(visualization_intent, dict):
            return "Visualization intent response must be a dictionary."

        required_keys = [
            "visualization_requested",
            "requested_chart_type",
        ]

        missing_keys = [
            key
            for key in required_keys
            if key not in visualization_intent
        ]

        if missing_keys:
            return (
                "Visualization intent response is missing key(s): "
                f"{missing_keys}."
            )

        if not isinstance(visualization_intent["visualization_requested"], bool):
            return "visualization_requested must be a boolean."

        return None

    @staticmethod
    def _validate_result_analysis(result_analysis: Any) -> str | None:
        if not isinstance(result_analysis, dict):
            return "Result analysis response must be a dictionary."

        required_keys = [
            "result_type",
            "recommended_visualization",
            "is_visualizable",
            "x_axis",
            "y_axis",
            "confidence",
            "reason",
        ]

        missing_keys = [
            key
            for key in required_keys
            if key not in result_analysis
        ]

        if missing_keys:
            return (
                "Result analysis response is missing key(s): "
                f"{missing_keys}."
            )

        if not isinstance(result_analysis["is_visualizable"], bool):
            return "result_analysis.is_visualizable must be a boolean."

        return None

    @staticmethod
    def _validate_chart_selection(chart_selection: Any) -> str | None:
        if not isinstance(chart_selection, dict):
            return "Chart selection response must be a dictionary."

        required_keys = [
            "chart_generation_enabled",
            "final_chart_type",
            "chart_source",
        ]

        missing_keys = [
            key
            for key in required_keys
            if key not in chart_selection
        ]

        if missing_keys:
            return (
                "Chart selection response is missing key(s): "
                f"{missing_keys}."
            )

        if not isinstance(chart_selection["chart_generation_enabled"], bool):
            return "chart_selection.chart_generation_enabled must be a boolean."

        return None

    @staticmethod
    def _validate_chart_validation(chart_validation: Any) -> str | None:
        if not isinstance(chart_validation, dict):
            return "Chart validation response must be a dictionary."

        required_keys = [
            "has_warning",
            "warning_type",
            "message",
        ]

        missing_keys = [
            key
            for key in required_keys
            if key not in chart_validation
        ]

        if missing_keys:
            return (
                "Chart validation response is missing key(s): "
                f"{missing_keys}."
            )

        if not isinstance(chart_validation["has_warning"], bool):
            return "chart_validation.has_warning must be a boolean."

        return None

    @staticmethod
    def _resolve_row_count(agent_input: ChartAgentInput) -> int:
        if agent_input.row_count is not None:
            return agent_input.row_count

        return len(agent_input.results)

    @staticmethod
    def _upstream_execution_not_successful(
        *,
        agent_input: ChartAgentInput,
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

    def _data_quality_blocking_reason(
        self,
        agent_input: ChartAgentInput,
    ) -> str | None:
        normalized_quality_status = self._normalize_status(
            agent_input.data_quality_status
        )

        if normalized_quality_status in {
            "quality_failed",
            "quality_not_evaluated",
        }:
            return (
                "Chart generation was blocked because data quality evaluation "
                f"returned {normalized_quality_status}."
            )

        if agent_input.is_result_usable is False:
            return (
                "Chart generation was blocked because the Data Quality Agent "
                "marked the result as not usable."
            )

        if agent_input.is_result_empty is True:
            return (
                "Chart generation was blocked because the query result is empty."
            )

        if agent_input.is_result_too_large is True:
            return (
                "Chart generation was blocked because the query result is too "
                "large for a clear chart."
            )

        if agent_input.has_visualization_warnings is True:
            quality_warnings = self._quality_warnings_as_dicts(
                agent_input.quality_warnings
            )

            if not quality_warnings:
                return (
                    "Chart generation was blocked because the Data Quality Agent "
                    "reported visualization warnings without enough detail to "
                    "treat them as non-blocking."
                )

            if any(
                self._normalize_status(warning.get("severity")) == "critical"
                for warning in quality_warnings
            ):
                return (
                    "Chart generation was blocked because the Data Quality Agent "
                    "reported critical visualization warnings."
                )

        return None

    def _non_blocking_quality_chart_warnings(
        self,
        agent_input: ChartAgentInput,
    ) -> list[ChartWarning]:
        if agent_input.has_visualization_warnings is not True:
            return []

        quality_warnings = self._quality_warnings_as_dicts(
            agent_input.quality_warnings
        )

        if not quality_warnings:
            return []

        return [
            ChartWarning(
                warning_type="data_quality_visualization_warning",
                severity=ChartWarningSeverity.WARNING,
                message=(
                    "The Data Quality Agent reported non-critical visualization "
                    "warnings for this result."
                ),
                source="data_quality_agent",
                recommendation=(
                    "Review the data-quality warnings before presenting this "
                    "chart to the user."
                ),
                metadata={
                    "quality_warnings": quality_warnings,
                },
            )
        ]

    @staticmethod
    def _warnings_from_chart_validation(
        chart_validation: dict[str, Any],
    ) -> list[ChartWarning]:
        if chart_validation.get("has_warning") is not True:
            return []

        return [
            ChartWarning(
                warning_type=chart_validation.get("warning_type")
                or "chart_validation_warning",
                severity=ChartWarningSeverity.WARNING,
                message=chart_validation.get("message")
                or "Chart validation produced a warning.",
                source="chart_validator",
                recommendation=(
                    "Review the generated chart before presenting it as the "
                    "best visualization."
                ),
                metadata={
                    "chart_validation": chart_validation,
                },
            )
        ]

    @staticmethod
    def _quality_warnings_as_dicts(
        quality_warnings: list[Any],
    ) -> list[dict[str, Any]]:
        normalized_warnings: list[dict[str, Any]] = []

        for warning in quality_warnings:
            if isinstance(warning, dict):
                normalized_warnings.append(warning)
                continue

            if hasattr(warning, "model_dump"):
                normalized_warnings.append(warning.model_dump(mode="json"))

        return normalized_warnings

    @staticmethod
    def _is_chart_recommended(result_analysis: dict[str, Any]) -> bool:
        recommended_visualization = result_analysis.get(
            "recommended_visualization"
        )

        return (
            result_analysis.get("is_visualizable") is True
            and recommended_visualization is not None
            and recommended_visualization != "table"
        )

    @staticmethod
    def _first_warning(
        chart_warnings: list[ChartWarning],
    ) -> ChartWarning | None:
        if not chart_warnings:
            return None

        return chart_warnings[0]

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
        agent_input: ChartAgentInput,
        start_time: float,
        row_count: int,
        normalized_execution_status: str | None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            **agent_input.metadata,
            "request_id": agent_input.request_id,
            "agent": "ChartAgent",
            "services": [
                "detect_visualization_intent",
                "analyze_results",
                "select_chart",
                "build_chart_payload",
                "validate_chart_selection",
            ],
            "row_count": row_count,
            "upstream_success": agent_input.success,
            "upstream_execution_success": agent_input.execution_success,
            "upstream_executed": agent_input.executed,
            "upstream_execution_status": normalized_execution_status,
            "upstream_error_type": agent_input.error_type,
            "data_quality_status": self._normalize_status(
                agent_input.data_quality_status
            ),
            "is_result_usable": agent_input.is_result_usable,
            "is_result_empty": agent_input.is_result_empty,
            "is_result_too_large": agent_input.is_result_too_large,
            "has_visualization_warnings": (
                agent_input.has_visualization_warnings
            ),
            "quality_metadata": agent_input.quality_metadata,
            "chart_agent_execution_time_ms": self._elapsed_ms(start_time),
            **(extra_metadata or {}),
        }

    @staticmethod
    def _elapsed_ms(start_time: float) -> float:
        return round((time.perf_counter() - start_time) * 1000, 3)