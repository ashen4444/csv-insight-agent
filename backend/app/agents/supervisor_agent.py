# backend/app/agents/supervisor_agent.py

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field
    
try:
    from langgraph.graph import END, START, StateGraph
except ModuleNotFoundError:  # pragma: no cover - tested through runtime failure message
    END = None
    START = None
    StateGraph = None

from app.agents.answer_formatter_agent import (
    AnswerFormatterAgent,
    AnswerFormatterAgentInput,
)
from app.agents.chart_agent import (
    ChartAgent,
    ChartAgentInput,
)
from app.agents.data_quality_agent import (
    DataQualityAgent,
    DataQualityAgentInput,
)
from app.agents.intent_router import IntentRouterAgent
from app.agents.intent_router.models import QueryIntent
from app.agents.query_executor_agent import (
    QueryExecutorAgent,
    QueryExecutorAgentInput,
)
from app.agents.sql_validator_agent import (
    SQLValidatorAgent,
    SQLValidatorAgentInput,
)
from app.agents.text_to_sql_agent import (
    TextToSQLAgent,
    TextToSQLAgentInput,
)

logger = logging.getLogger(__name__)


class SupervisorWorkflowStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class SupervisorErrorType(str, Enum):
    LANGGRAPH_UNAVAILABLE = "langgraph_unavailable"
    ROUTING_FAILED = "routing_failed"
    UNSUPPORTED_WORKFLOW_PATH = "unsupported_workflow_path"
    SQL_GENERATION_FAILED = "sql_generation_failed"
    SQL_VALIDATION_BLOCKED = "sql_validation_blocked"
    SQL_VALIDATION_FAILED = "sql_validation_failed"
    QUERY_EXECUTION_FAILED = "query_execution_failed"
    DATA_QUALITY_BLOCKED = "data_quality_blocked"
    DATA_QUALITY_FAILED = "data_quality_failed"
    ANSWER_FORMATTING_FAILED = "answer_formatting_failed"
    UNEXPECTED_SUPERVISOR_ERROR = "unexpected_supervisor_error"


class SupervisorAgentInput(BaseModel):
    """
    Public Supervisor input boundary.

    Important:
    - Do not accept schema_context.
    - Do not accept schema_profile.
    - Do not accept table_name.
    - Do not accept allowed_columns.
    - Trusted metadata must be resolved inside downstream agents from dataset_id.
    """

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)

    request_id: str | None = None

    chart_generation_approved: bool = False
    approved_chart_type: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


class SupervisorAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool

    dataset_id: str
    question: str

    final_response: dict[str, Any]

    workflow_status: SupervisorWorkflowStatus
    executed_agents: list[str] = Field(default_factory=list)
    skipped_agents: list[str] = Field(default_factory=list)

    failed_agent: str | None = None
    error_type: SupervisorErrorType | None = None
    error_message: str | None = None
    blocking_reason: str | None = None

    execution_time_ms: float

    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SupervisorWorkflowState(TypedDict, total=False):
    dataset_id: str
    question: str
    request_id: str | None

    chart_generation_approved: bool
    approved_chart_type: str | None

    metadata: dict[str, Any]

    intent_router_output: Any
    text_to_sql_output: Any
    sql_validator_output: Any
    query_executor_output: Any
    data_quality_output: Any
    chart_agent_output: Any
    answer_formatter_input: Any
    answer_formatter_output: Any

    workflow_status: str
    current_step: str | None
    executed_agents: list[str]

    failed_agent: str | None
    error_type: str | None
    error_message: str | None
    blocking_reason: str | None

    supervisor_routing_blocked: bool


class SupervisorAgent:
    """
    LangGraph-powered workflow Supervisor for CSV Insight Agent.

    Responsibilities:
    - Run Intent Router first.
    - Choose the correct workflow path.
    - Call only the agents needed for the current request.
    - Stop early on blocking/failure states.
    - Preserve upstream agent outputs.
    - Map upstream outputs into AnswerFormatterAgentInput.
    - Return a frontend-friendly final response.

    Non-responsibilities:
    - SQL generation.
    - SQL validation.
    - SQL execution.
    - Data-quality evaluation.
    - Chart payload creation.
    - Final answer formatting.
    - Data cleaning or mutation.
    """

    WORKFLOW_AGENTS = [
        "IntentRouterAgent",
        "TextToSQLAgent",
        "SQLValidatorAgent",
        "QueryExecutorAgent",
        "DataQualityAgent",
        "ChartAgent",
        "AnswerFormatterAgent",
    ]

    MAIN_SQL_WORKFLOW_INTENTS = {
        QueryIntent.ANALYTICS_QUERY.value,
        QueryIntent.VISUALIZATION_QUERY.value,
    }

    def __init__(
        self,
        intent_router: IntentRouterAgent | None = None,
        text_to_sql_agent: TextToSQLAgent | None = None,
        sql_validator_agent: SQLValidatorAgent | None = None,
        query_executor_agent: QueryExecutorAgent | None = None,
        data_quality_agent: DataQualityAgent | None = None,
        chart_agent: ChartAgent | None = None,
        answer_formatter_agent: AnswerFormatterAgent | None = None,
    ) -> None:
        self.intent_router = intent_router or IntentRouterAgent()
        self.text_to_sql_agent = text_to_sql_agent or TextToSQLAgent()
        self.sql_validator_agent = sql_validator_agent or SQLValidatorAgent()
        self.query_executor_agent = query_executor_agent or QueryExecutorAgent()
        self.data_quality_agent = data_quality_agent or DataQualityAgent()
        self.chart_agent = chart_agent or ChartAgent()
        self.answer_formatter_agent = (
            answer_formatter_agent or AnswerFormatterAgent()
        )

        self.workflow = self._build_workflow()

    def run(
        self,
        agent_input: SupervisorAgentInput | dict[str, Any],
    ) -> SupervisorAgentOutput:
        start_time = time.perf_counter()
        parsed_input = self._parse_input(agent_input)

        initial_state = self._initial_state(parsed_input)

        try:
            final_state = self.workflow.invoke(initial_state)
        except Exception as exc:
            logger.exception("Unexpected Supervisor workflow failure.")

            failure_state: SupervisorWorkflowState = {
                **initial_state,
                "workflow_status": SupervisorWorkflowStatus.FAILED.value,
                "failed_agent": "SupervisorAgent",
                "error_type": SupervisorErrorType.UNEXPECTED_SUPERVISOR_ERROR.value,
                "error_message": str(exc),
                "blocking_reason": (
                    "The Supervisor workflow failed before the normal "
                    "Answer Formatter step completed."
                ),
                "supervisor_routing_blocked": True,
            }

            final_state = {
                **failure_state,
                **self._format_answer(failure_state),
            }

        return self._to_supervisor_output(
            state=final_state,
            start_time=start_time,
        )

    def orchestrate(
        self,
        agent_input: SupervisorAgentInput | dict[str, Any],
    ) -> SupervisorAgentOutput:
        return self.run(agent_input)

    def _build_workflow(self) -> Any:
        if StateGraph is None or START is None or END is None:
            raise RuntimeError(
                "LangGraph is required for SupervisorAgent. "
                "Install it with: pip install langgraph"
            )

        workflow = StateGraph(SupervisorWorkflowState)

        workflow.add_node("route_intent", self._route_intent)
        workflow.add_node("generate_sql", self._generate_sql)
        workflow.add_node("validate_sql", self._validate_sql)
        workflow.add_node("execute_query", self._execute_query)
        workflow.add_node("evaluate_data_quality", self._evaluate_data_quality)
        workflow.add_node("build_chart", self._build_chart)
        workflow.add_node("format_answer", self._format_answer)

        workflow.add_edge(START, "route_intent")

        workflow.add_conditional_edges(
            "route_intent",
            self._next_after_intent,
            {
                "generate_sql": "generate_sql",
                "format_answer": "format_answer",
            },
        )

        workflow.add_conditional_edges(
            "generate_sql",
            self._next_after_sql_generation,
            {
                "validate_sql": "validate_sql",
                "format_answer": "format_answer",
            },
        )

        workflow.add_conditional_edges(
            "validate_sql",
            self._next_after_sql_validation,
            {
                "execute_query": "execute_query",
                "format_answer": "format_answer",
            },
        )

        workflow.add_conditional_edges(
            "execute_query",
            self._next_after_query_execution,
            {
                "evaluate_data_quality": "evaluate_data_quality",
                "format_answer": "format_answer",
            },
        )

        workflow.add_conditional_edges(
            "evaluate_data_quality",
            self._next_after_data_quality,
            {
                "build_chart": "build_chart",
                "format_answer": "format_answer",
            },
        )

        workflow.add_edge("build_chart", "format_answer")
        workflow.add_edge("format_answer", END)

        return workflow.compile()

    def _route_intent(
        self,
        state: SupervisorWorkflowState,
    ) -> dict[str, Any]:
        agent_name = "IntentRouterAgent"

        try:
            output = self.intent_router.classify(state["question"])
            output_dict = self._to_serialized_dict(output)

            updates: dict[str, Any] = {
                "intent_router_output": output,
                "workflow_status": SupervisorWorkflowStatus.RUNNING.value,
                "current_step": agent_name,
                "supervisor_routing_blocked": False,
            }

            if self._should_stop_after_intent(output_dict):
                updates.update(
                    {
                        "workflow_status": SupervisorWorkflowStatus.BLOCKED.value,
                        "blocking_reason": (
                            output_dict.get("blocking_reason")
                            or output_dict.get("unsupported_reason")
                            or output_dict.get("clarification_question")
                            or "Intent Router stopped the workflow."
                        ),
                    }
                )

            elif not self._is_supported_main_workflow(output_dict):
                primary_intent = output_dict.get("primary_intent")
                blocking_reason = (
                    f"Supervisor v1 does not yet support the "
                    f"{primary_intent!r} workflow path. "
                    "Analytics and visualization workflows are supported now. "
                    "Schema/table-preview/data-quality-only routing should be "
                    "mapped after extending the Answer Formatter input."
                )

                updates.update(
                    {
                        "workflow_status": SupervisorWorkflowStatus.BLOCKED.value,
                        "error_type": (
                            SupervisorErrorType.UNSUPPORTED_WORKFLOW_PATH.value
                        ),
                        "blocking_reason": blocking_reason,
                        "supervisor_routing_blocked": True,
                    }
                )

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates=updates,
            )

        except Exception as exc:
            logger.exception("Intent Router failed inside Supervisor.")

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates={
                    "workflow_status": SupervisorWorkflowStatus.FAILED.value,
                    "failed_agent": agent_name,
                    "error_type": SupervisorErrorType.ROUTING_FAILED.value,
                    "error_message": str(exc),
                    "blocking_reason": (
                        "Intent routing failed before the workflow path could "
                        "be selected."
                    ),
                    "supervisor_routing_blocked": True,
                },
            )

    def _generate_sql(
        self,
        state: SupervisorWorkflowState,
    ) -> dict[str, Any]:
        agent_name = "TextToSQLAgent"

        try:
            output = self.text_to_sql_agent.generate(
                TextToSQLAgentInput(
                    dataset_id=state["dataset_id"],
                    question=state["question"],
                    request_id=state.get("request_id"),
                    metadata=self._node_metadata(state, agent_name),
                )
            )
            output_dict = self._to_serialized_dict(output)

            updates: dict[str, Any] = {
                "text_to_sql_output": output,
                "workflow_status": SupervisorWorkflowStatus.RUNNING.value,
                "current_step": agent_name,
            }

            if output_dict.get("success") is not True:
                updates.update(
                    {
                        "workflow_status": SupervisorWorkflowStatus.FAILED.value,
                        "failed_agent": agent_name,
                        "error_type": (
                            SupervisorErrorType.SQL_GENERATION_FAILED.value
                        ),
                        "error_message": output_dict.get("error_message"),
                        "blocking_reason": (
                            output_dict.get("error_message")
                            or "Text-to-SQL generation failed."
                        ),
                    }
                )

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates=updates,
            )

        except Exception as exc:
            logger.exception("Text-to-SQL Agent failed inside Supervisor.")

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates={
                    "workflow_status": SupervisorWorkflowStatus.FAILED.value,
                    "failed_agent": agent_name,
                    "error_type": SupervisorErrorType.SQL_GENERATION_FAILED.value,
                    "error_message": str(exc),
                    "blocking_reason": "Text-to-SQL generation failed unexpectedly.",
                },
            )

    def _validate_sql(
        self,
        state: SupervisorWorkflowState,
    ) -> dict[str, Any]:
        agent_name = "SQLValidatorAgent"
        text_to_sql_output = self._to_serialized_dict(
            state.get("text_to_sql_output")
        )

        try:
            output = self.sql_validator_agent.validate(
                SQLValidatorAgentInput(
                    dataset_id=state["dataset_id"],
                    question=state["question"],
                    sql=text_to_sql_output.get("sql") or "",
                    request_id=state.get("request_id"),
                    metadata=self._node_metadata(state, agent_name),
                )
            )
            output_dict = self._to_serialized_dict(output)
            validation_status = self._normalize_status(
                output_dict.get("validation_status")
            )

            updates: dict[str, Any] = {
                "sql_validator_output": output,
                "workflow_status": SupervisorWorkflowStatus.RUNNING.value,
                "current_step": agent_name,
            }

            if output_dict.get("success") is not True:
                if validation_status == "blocked":
                    workflow_status = SupervisorWorkflowStatus.BLOCKED.value
                    error_type = SupervisorErrorType.SQL_VALIDATION_BLOCKED.value
                else:
                    workflow_status = SupervisorWorkflowStatus.FAILED.value
                    error_type = SupervisorErrorType.SQL_VALIDATION_FAILED.value

                updates.update(
                    {
                        "workflow_status": workflow_status,
                        "failed_agent": agent_name,
                        "error_type": error_type,
                        "error_message": output_dict.get("error_message"),
                        "blocking_reason": (
                            output_dict.get("blocking_reason")
                            or output_dict.get("error_message")
                            or "SQL validation did not pass."
                        ),
                    }
                )

            elif output_dict.get("is_safe_to_execute") is not True:
                updates.update(
                    {
                        "workflow_status": SupervisorWorkflowStatus.BLOCKED.value,
                        "failed_agent": agent_name,
                        "error_type": (
                            SupervisorErrorType.SQL_VALIDATION_BLOCKED.value
                        ),
                        "error_message": output_dict.get("error_message"),
                        "blocking_reason": (
                            output_dict.get("blocking_reason")
                            or "SQL was not marked safe to execute."
                        ),
                    }
                )

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates=updates,
            )

        except Exception as exc:
            logger.exception("SQL Validator Agent failed inside Supervisor.")

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates={
                    "workflow_status": SupervisorWorkflowStatus.FAILED.value,
                    "failed_agent": agent_name,
                    "error_type": SupervisorErrorType.SQL_VALIDATION_FAILED.value,
                    "error_message": str(exc),
                    "blocking_reason": "SQL validation failed unexpectedly.",
                },
            )

    def _execute_query(
        self,
        state: SupervisorWorkflowState,
    ) -> dict[str, Any]:
        agent_name = "QueryExecutorAgent"
        validator_output = self._to_serialized_dict(
            state.get("sql_validator_output")
        )

        try:
            output = self.query_executor_agent.execute(
                QueryExecutorAgentInput(
                    dataset_id=state["dataset_id"],
                    question=state["question"],
                    sql=validator_output.get("sql") or "",
                    is_safe_to_execute=bool(
                        validator_output.get("is_safe_to_execute")
                    ),
                    validation_status=validator_output.get("validation_status"),
                    request_id=state.get("request_id"),
                    metadata=self._node_metadata(state, agent_name),
                )
            )
            output_dict = self._to_serialized_dict(output)

            updates: dict[str, Any] = {
                "query_executor_output": output,
                "workflow_status": SupervisorWorkflowStatus.RUNNING.value,
                "current_step": agent_name,
            }

            if (
                output_dict.get("success") is not True
                or output_dict.get("executed") is not True
            ):
                updates.update(
                    {
                        "workflow_status": SupervisorWorkflowStatus.FAILED.value,
                        "failed_agent": agent_name,
                        "error_type": (
                            SupervisorErrorType.QUERY_EXECUTION_FAILED.value
                        ),
                        "error_message": output_dict.get("error_message"),
                        "blocking_reason": (
                            output_dict.get("blocking_reason")
                            or output_dict.get("error_message")
                            or "Query execution did not succeed."
                        ),
                    }
                )

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates=updates,
            )

        except Exception as exc:
            logger.exception("Query Executor Agent failed inside Supervisor.")

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates={
                    "workflow_status": SupervisorWorkflowStatus.FAILED.value,
                    "failed_agent": agent_name,
                    "error_type": SupervisorErrorType.QUERY_EXECUTION_FAILED.value,
                    "error_message": str(exc),
                    "blocking_reason": "Query execution failed unexpectedly.",
                },
            )

    def _evaluate_data_quality(
        self,
        state: SupervisorWorkflowState,
    ) -> dict[str, Any]:
        agent_name = "DataQualityAgent"
        execution_output = self._to_serialized_dict(
            state.get("query_executor_output")
        )

        try:
            output = self.data_quality_agent.evaluate(
                DataQualityAgentInput(
                    dataset_id=state["dataset_id"],
                    question=state["question"],
                    sql=execution_output.get("sql"),
                    results=execution_output.get("results") or [],
                    row_count=execution_output.get("row_count"),
                    success=execution_output.get("success"),
                    execution_success=execution_output.get("success"),
                    executed=execution_output.get("executed"),
                    execution_status=execution_output.get("execution_status"),
                    execution_time_ms=execution_output.get("execution_time_ms"),
                    error_type=execution_output.get("error_type"),
                    error_message=execution_output.get("error_message"),
                    blocking_reason=execution_output.get("blocking_reason"),
                    request_id=state.get("request_id"),
                    metadata=self._node_metadata(state, agent_name),
                )
            )
            output_dict = self._to_serialized_dict(output)

            updates: dict[str, Any] = {
                "data_quality_output": output,
                "workflow_status": SupervisorWorkflowStatus.RUNNING.value,
                "current_step": agent_name,
            }

            if output_dict.get("success") is not True:
                normalized_quality_status = self._normalize_status(
                    output_dict.get("quality_status")
                )

                if (
                    output_dict.get("is_result_usable") is False
                    or normalized_quality_status == "quality_not_evaluated"
                ):
                    workflow_status = SupervisorWorkflowStatus.BLOCKED.value
                    error_type = SupervisorErrorType.DATA_QUALITY_BLOCKED.value
                else:
                    workflow_status = SupervisorWorkflowStatus.FAILED.value
                    error_type = SupervisorErrorType.DATA_QUALITY_FAILED.value

                updates.update(
                    {
                        "workflow_status": workflow_status,
                        "failed_agent": agent_name,
                        "error_type": error_type,
                        "error_message": output_dict.get("error_message"),
                        "blocking_reason": (
                            output_dict.get("blocking_reason")
                            or output_dict.get("error_message")
                            or "Data quality evaluation did not pass."
                        ),
                    }
                )

            elif output_dict.get("is_result_usable") is not True:
                updates.update(
                    {
                        "workflow_status": SupervisorWorkflowStatus.BLOCKED.value,
                        "failed_agent": agent_name,
                        "error_type": SupervisorErrorType.DATA_QUALITY_BLOCKED.value,
                        "error_message": output_dict.get("error_message"),
                        "blocking_reason": (
                            output_dict.get("blocking_reason")
                            or "Data Quality Agent marked the result as unusable."
                        ),
                    }
                )

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates=updates,
            )

        except Exception as exc:
            logger.exception("Data Quality Agent failed inside Supervisor.")

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates={
                    "workflow_status": SupervisorWorkflowStatus.FAILED.value,
                    "failed_agent": agent_name,
                    "error_type": SupervisorErrorType.DATA_QUALITY_FAILED.value,
                    "error_message": str(exc),
                    "blocking_reason": (
                        "Data quality evaluation failed unexpectedly."
                    ),
                },
            )

    def _build_chart(
        self,
        state: SupervisorWorkflowState,
    ) -> dict[str, Any]:
        agent_name = "ChartAgent"
        execution_output = self._to_serialized_dict(
            state.get("query_executor_output")
        )
        quality_output = self._to_serialized_dict(
            state.get("data_quality_output")
        )
        router_output = self._to_serialized_dict(
            state.get("intent_router_output")
        )

        chart_generation_approved = bool(
            state.get("chart_generation_approved")
        ) or (
            router_output.get("primary_intent")
            == QueryIntent.VISUALIZATION_QUERY.value
        )

        try:
            output = self.chart_agent.generate(
                ChartAgentInput(
                    dataset_id=state["dataset_id"],
                    question=state["question"],
                    sql=execution_output.get("sql"),
                    results=execution_output.get("results") or [],
                    row_count=execution_output.get("row_count"),
                    success=execution_output.get("success"),
                    execution_success=execution_output.get("success"),
                    executed=execution_output.get("executed"),
                    execution_status=execution_output.get("execution_status"),
                    execution_time_ms=execution_output.get("execution_time_ms"),
                    data_quality_status=quality_output.get("quality_status"),
                    is_result_usable=quality_output.get("is_result_usable"),
                    is_result_empty=quality_output.get("is_result_empty"),
                    is_result_too_large=quality_output.get("is_result_too_large"),
                    has_visualization_warnings=quality_output.get(
                        "has_visualization_warnings"
                    ),
                    quality_warnings=quality_output.get("warnings") or [],
                    quality_recommendations=(
                        quality_output.get("recommendations") or []
                    ),
                    quality_metadata=quality_output.get("metadata") or {},
                    chart_generation_approved=chart_generation_approved,
                    approved_chart_type=state.get("approved_chart_type"),
                    error_type=execution_output.get("error_type"),
                    error_message=execution_output.get("error_message"),
                    blocking_reason=execution_output.get("blocking_reason"),
                    request_id=state.get("request_id"),
                    metadata=self._node_metadata(state, agent_name),
                )
            )

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates={
                    "chart_agent_output": output,
                    "workflow_status": SupervisorWorkflowStatus.RUNNING.value,
                    "current_step": agent_name,
                },
            )

        except Exception as exc:
            logger.exception("Chart Agent failed inside Supervisor.")

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates={
                    "workflow_status": SupervisorWorkflowStatus.RUNNING.value,
                    "current_step": agent_name,
                    "chart_agent_output": {
                        "success": False,
                        "dataset_id": state["dataset_id"],
                        "question": state["question"],
                        "sql": execution_output.get("sql"),
                        "chart_generation_status": "chart_failed",
                        "chart_generation_enabled": False,
                        "chart_type": None,
                        "selected_chart_type": None,
                        "requested_chart_type": state.get("approved_chart_type"),
                        "recommended_chart_type": None,
                        "chart_payload": None,
                        "chart_warning": {
                            "warning_type": "unexpected_chart_error",
                            "severity": "critical",
                            "message": str(exc),
                            "source": "chart_agent",
                            "recommendation": (
                                "Review the Chart Agent failure before "
                                "retrying chart generation."
                            ),
                            "metadata": {
                                "exception_type": type(exc).__name__,
                            },
                        },
                        "chart_warnings": [],
                        "is_chart_available": False,
                        "is_chart_recommended": False,
                        "visualization_intent": {},
                        "result_analysis": {},
                        "chart_selection": {},
                        "error_type": "unexpected_chart_error",
                        "error_message": str(exc),
                        "blocking_reason": (
                            "Chart generation failed unexpectedly."
                        ),
                        "metadata": self._node_metadata(state, agent_name),
                    },
                },
            )

    def _format_answer(
        self,
        state: SupervisorWorkflowState,
    ) -> dict[str, Any]:
        agent_name = "AnswerFormatterAgent"

        try:
            formatter_input = self._build_answer_formatter_input(state)
            output = self.answer_formatter_agent.format(formatter_input)

            current_status = state.get("workflow_status")
            next_status = current_status

            if current_status == SupervisorWorkflowStatus.RUNNING.value:
                next_status = SupervisorWorkflowStatus.COMPLETED.value

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates={
                    "answer_formatter_input": formatter_input,
                    "answer_formatter_output": output,
                    "workflow_status": next_status,
                    "current_step": agent_name,
                },
            )

        except Exception as exc:
            logger.exception("Answer Formatter Agent failed inside Supervisor.")

            return self._with_executed_agent(
                state=state,
                agent_name=agent_name,
                updates={
                    "workflow_status": SupervisorWorkflowStatus.FAILED.value,
                    "failed_agent": agent_name,
                    "error_type": (
                        SupervisorErrorType.ANSWER_FORMATTING_FAILED.value
                    ),
                    "error_message": str(exc),
                    "blocking_reason": "Answer formatting failed unexpectedly.",
                    "answer_formatter_output": self._emergency_final_response(
                        state=state,
                        message=(
                            "The workflow ran, but the final answer could not "
                            "be formatted."
                        ),
                        error_message=str(exc),
                    ),
                },
            )

    def _next_after_intent(
        self,
        state: SupervisorWorkflowState,
    ) -> str:
        if self._workflow_should_stop(state):
            return "format_answer"

        return "generate_sql"

    def _next_after_sql_generation(
        self,
        state: SupervisorWorkflowState,
    ) -> str:
        if self._workflow_should_stop(state):
            return "format_answer"

        return "validate_sql"

    def _next_after_sql_validation(
        self,
        state: SupervisorWorkflowState,
    ) -> str:
        if self._workflow_should_stop(state):
            return "format_answer"

        return "execute_query"

    def _next_after_query_execution(
        self,
        state: SupervisorWorkflowState,
    ) -> str:
        if self._workflow_should_stop(state):
            return "format_answer"

        return "evaluate_data_quality"

    def _next_after_data_quality(
        self,
        state: SupervisorWorkflowState,
    ) -> str:
        if self._workflow_should_stop(state):
            return "format_answer"

        quality_output = self._to_serialized_dict(
            state.get("data_quality_output")
        )

        if (
            quality_output.get("success") is True
            and quality_output.get("is_result_usable") is True
        ):
            return "build_chart"

        return "format_answer"

    @staticmethod
    def _parse_input(
        agent_input: SupervisorAgentInput | dict[str, Any],
    ) -> SupervisorAgentInput:
        if isinstance(agent_input, SupervisorAgentInput):
            return agent_input

        return SupervisorAgentInput.model_validate(agent_input)

    @staticmethod
    def _initial_state(
        agent_input: SupervisorAgentInput,
    ) -> SupervisorWorkflowState:
        return {
            "dataset_id": agent_input.dataset_id,
            "question": agent_input.question,
            "request_id": agent_input.request_id,
            "chart_generation_approved": agent_input.chart_generation_approved,
            "approved_chart_type": agent_input.approved_chart_type,
            "metadata": agent_input.metadata,
            "workflow_status": SupervisorWorkflowStatus.RUNNING.value,
            "current_step": None,
            "executed_agents": [],
            "failed_agent": None,
            "error_type": None,
            "error_message": None,
            "blocking_reason": None,
            "supervisor_routing_blocked": False,
        }

    def _build_answer_formatter_input(
        self,
        state: SupervisorWorkflowState,
    ) -> AnswerFormatterAgentInput:
        router_output = self._to_serialized_dict(
            state.get("intent_router_output")
        )
        text_to_sql_output = self._to_serialized_dict(
            state.get("text_to_sql_output")
        )
        validator_output = self._to_serialized_dict(
            state.get("sql_validator_output")
        )
        executor_output = self._to_serialized_dict(
            state.get("query_executor_output")
        )
        quality_output = self._to_serialized_dict(
            state.get("data_quality_output")
        )
        chart_output = self._to_serialized_dict(
            state.get("chart_agent_output")
        )

        supervisor_routing_blocked = bool(
            state.get("supervisor_routing_blocked")
        )

        is_routable = router_output.get("is_routable", True)
        routing_blocking_reason = router_output.get("blocking_reason")

        if supervisor_routing_blocked:
            is_routable = False
            routing_blocking_reason = state.get("blocking_reason")

        sql_generation_success = text_to_sql_output.get("success")
        sql_generation_error_type = text_to_sql_output.get("error_type")
        sql_generation_error_message = text_to_sql_output.get("error_message")

        if (
            state.get("failed_agent") == "TextToSQLAgent"
            and not text_to_sql_output
        ):
            sql_generation_success = False
            sql_generation_error_type = "sql_generation_failed"
            sql_generation_error_message = state.get("error_message")

        validation_success = validator_output.get("success")
        validation_status = validator_output.get("validation_status")
        validation_error_type = validator_output.get("error_type")
        validation_error_message = validator_output.get("error_message")
        validation_blocking_reason = validator_output.get("blocking_reason")

        if (
            state.get("failed_agent") == "SQLValidatorAgent"
            and not validator_output
        ):
            validation_success = False
            validation_status = "error"
            validation_error_type = "sql_validation_failed"
            validation_error_message = state.get("error_message")
            validation_blocking_reason = state.get("blocking_reason")

        execution_success = executor_output.get("success")
        execution_status = executor_output.get("execution_status")
        executed = executor_output.get("executed")
        execution_error_type = executor_output.get("error_type")
        execution_error_message = executor_output.get("error_message")
        execution_blocking_reason = executor_output.get("blocking_reason")

        if (
            state.get("failed_agent") == "QueryExecutorAgent"
            and not executor_output
        ):
            execution_success = False
            execution_status = "execution_failed"
            executed = False
            execution_error_type = "query_execution_failed"
            execution_error_message = state.get("error_message")
            execution_blocking_reason = state.get("blocking_reason")

        data_quality_success = quality_output.get("success")
        quality_status = quality_output.get("quality_status")
        quality_error_type = quality_output.get("error_type")
        quality_error_message = quality_output.get("error_message")
        quality_blocking_reason = quality_output.get("blocking_reason")

        if (
            state.get("failed_agent") == "DataQualityAgent"
            and not quality_output
        ):
            data_quality_success = False
            quality_status = "quality_failed"
            quality_error_type = "data_quality_failed"
            quality_error_message = state.get("error_message")
            quality_blocking_reason = state.get("blocking_reason")

        return AnswerFormatterAgentInput(
            dataset_id=state["dataset_id"],
            question=state["question"],
            request_id=state.get("request_id"),
            primary_intent=router_output.get("primary_intent"),
            required_capabilities=router_output.get("required_capabilities") or [],
            routing_confidence=router_output.get("confidence"),
            routing_reason=router_output.get("reason"),
            routing_source=router_output.get("source"),
            needs_clarification=bool(
                router_output.get("needs_clarification", False)
            ),
            clarification_question=router_output.get(
                "clarification_question"
            ),
            is_routable=bool(is_routable),
            routing_blocking_reason=routing_blocking_reason,
            unsupported_reason=router_output.get("unsupported_reason"),
            sql=self._first_non_empty(
                executor_output.get("sql"),
                validator_output.get("sql"),
                text_to_sql_output.get("sql"),
            ),
            sql_generation_success=sql_generation_success,
            sql_generation_error_type=sql_generation_error_type,
            sql_generation_error_message=sql_generation_error_message,
            validation_success=validation_success,
            validation_status=validation_status,
            is_valid=validator_output.get("is_valid"),
            is_safe_to_execute=validator_output.get("is_safe_to_execute"),
            validation_error_type=validation_error_type,
            validation_error_message=validation_error_message,
            validation_blocking_reason=validation_blocking_reason,
            execution_success=execution_success,
            execution_status=execution_status,
            executed=executed,
            results=executor_output.get("results") or [],
            row_count=executor_output.get("row_count"),
            execution_time_ms=executor_output.get("execution_time_ms"),
            execution_error_type=execution_error_type,
            execution_error_message=execution_error_message,
            execution_blocking_reason=execution_blocking_reason,
            data_quality_success=data_quality_success,
            quality_status=quality_status,
            is_result_usable=quality_output.get("is_result_usable"),
            is_result_empty=quality_output.get("is_result_empty"),
            is_result_too_large=quality_output.get("is_result_too_large"),
            has_null_warnings=quality_output.get("has_null_warnings"),
            has_duplicate_warnings=quality_output.get(
                "has_duplicate_warnings"
            ),
            has_visualization_warnings=quality_output.get(
                "has_visualization_warnings"
            ),
            quality_warnings=quality_output.get("warnings") or [],
            quality_recommendations=(
                quality_output.get("recommendations") or []
            ),
            quality_error_type=quality_error_type,
            quality_error_message=quality_error_message,
            quality_blocking_reason=quality_blocking_reason,
            chart_success=chart_output.get("success"),
            chart_generation_status=chart_output.get(
                "chart_generation_status"
            ),
            chart_generation_enabled=chart_output.get(
                "chart_generation_enabled"
            ),
            chart_type=chart_output.get("chart_type"),
            selected_chart_type=chart_output.get("selected_chart_type"),
            requested_chart_type=chart_output.get("requested_chart_type"),
            recommended_chart_type=chart_output.get("recommended_chart_type"),
            chart_payload=chart_output.get("chart_payload"),
            chart_warning=chart_output.get("chart_warning"),
            chart_warnings=chart_output.get("chart_warnings") or [],
            is_chart_available=chart_output.get("is_chart_available"),
            is_chart_recommended=chart_output.get("is_chart_recommended"),
            chart_error_type=chart_output.get("error_type"),
            chart_error_message=chart_output.get("error_message"),
            chart_blocking_reason=chart_output.get("blocking_reason"),
            metadata=self._formatter_metadata(
                state=state,
                router_output=router_output,
                text_to_sql_output=text_to_sql_output,
                validator_output=validator_output,
                executor_output=executor_output,
                quality_output=quality_output,
                chart_output=chart_output,
            ),
        )

    def _to_supervisor_output(
        self,
        *,
        state: SupervisorWorkflowState,
        start_time: float,
    ) -> SupervisorAgentOutput:
        final_response = self._to_serialized_dict(
            state.get("answer_formatter_output")
        )

        if not final_response:
            final_response = self._emergency_final_response(
                state=state,
                message="The workflow completed without a formatted response.",
                error_message=state.get("error_message"),
            )

        executed_agents = self._unique_list(state.get("executed_agents") or [])
        skipped_agents = [
            agent
            for agent in self.WORKFLOW_AGENTS
            if agent not in executed_agents
        ]

        workflow_status = SupervisorWorkflowStatus(
            state.get("workflow_status")
            or SupervisorWorkflowStatus.FAILED.value
        )

        return SupervisorAgentOutput(
            success=bool(final_response.get("success")) and (
                workflow_status != SupervisorWorkflowStatus.FAILED
            ),
            dataset_id=state["dataset_id"],
            question=state["question"],
            final_response=final_response,
            workflow_status=workflow_status,
            executed_agents=executed_agents,
            skipped_agents=skipped_agents,
            failed_agent=state.get("failed_agent"),
            error_type=self._supervisor_error_type(state.get("error_type")),
            error_message=state.get("error_message"),
            blocking_reason=state.get("blocking_reason"),
            execution_time_ms=self._elapsed_ms(start_time),
            metadata={
                **(state.get("metadata") or {}),
                "agent": "SupervisorAgent",
                "orchestration_framework": "LangGraph",
                "workflow_status": workflow_status.value,
                "executed_agents": executed_agents,
                "skipped_agents": skipped_agents,
                "failed_agent": state.get("failed_agent"),
                "final_response_status": final_response.get(
                    "response_status"
                ),
                "final_response_type": final_response.get("response_type"),
            },
        )

    @staticmethod
    def _should_stop_after_intent(
        router_output: dict[str, Any],
    ) -> bool:
        return (
            router_output.get("primary_intent")
            == QueryIntent.UNSUPPORTED_QUERY.value
            or router_output.get("needs_clarification") is True
            or router_output.get("is_routable") is False
        )

    def _is_supported_main_workflow(
        self,
        router_output: dict[str, Any],
    ) -> bool:
        return router_output.get("primary_intent") in self.MAIN_SQL_WORKFLOW_INTENTS

    @staticmethod
    def _workflow_should_stop(
        state: SupervisorWorkflowState,
    ) -> bool:
        return state.get("workflow_status") in {
            SupervisorWorkflowStatus.BLOCKED.value,
            SupervisorWorkflowStatus.FAILED.value,
        }

    @staticmethod
    def _with_executed_agent(
        *,
        state: SupervisorWorkflowState,
        agent_name: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **updates,
            "executed_agents": SupervisorAgent._unique_list(
                [*(state.get("executed_agents") or []), agent_name]
            ),
        }

    @staticmethod
    def _to_serialized_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}

        if isinstance(value, dict):
            return value

        if hasattr(value, "to_dict"):
            return value.to_dict()

        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")

        return {}

    @staticmethod
    def _normalize_status(value: Any) -> str | None:
        if value is None:
            return None

        if isinstance(value, Enum):
            raw_value = value.value
        else:
            raw_value = str(value)

        normalized_value = raw_value.strip().lower()

        return normalized_value or None

    @staticmethod
    def _supervisor_error_type(
        value: Any,
    ) -> SupervisorErrorType | None:
        if value is None:
            return None

        normalized_value = SupervisorAgent._normalize_status(value)

        try:
            return SupervisorErrorType(normalized_value)
        except ValueError:
            return SupervisorErrorType.UNEXPECTED_SUPERVISOR_ERROR

    @staticmethod
    def _first_non_empty(*values: Any) -> Any:
        for value in values:
            if value is not None and value != "":
                return value

        return None

    @staticmethod
    def _unique_list(values: list[str]) -> list[str]:
        unique_values: list[str] = []

        for value in values:
            if value not in unique_values:
                unique_values.append(value)

        return unique_values

    @staticmethod
    def _elapsed_ms(start_time: float) -> float:
        return round((time.perf_counter() - start_time) * 1000, 3)

    @staticmethod
    def _node_metadata(
        state: SupervisorWorkflowState,
        agent_name: str,
    ) -> dict[str, Any]:
        return {
            **(state.get("metadata") or {}),
            "request_id": state.get("request_id"),
            "supervisor_agent": "SupervisorAgent",
            "supervisor_current_node": agent_name,
        }

    def _formatter_metadata(
        self,
        *,
        state: SupervisorWorkflowState,
        router_output: dict[str, Any],
        text_to_sql_output: dict[str, Any],
        validator_output: dict[str, Any],
        executor_output: dict[str, Any],
        quality_output: dict[str, Any],
        chart_output: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **(state.get("metadata") or {}),
            "request_id": state.get("request_id"),
            "supervisor_agent": "SupervisorAgent",
            "workflow_status": state.get("workflow_status"),
            "executed_agents": state.get("executed_agents") or [],
            "failed_agent": state.get("failed_agent"),
            "supervisor_error_type": state.get("error_type"),
            "supervisor_error_message": state.get("error_message"),
            "supervisor_blocking_reason": state.get("blocking_reason"),
            "upstream_outputs": {
                "intent_router": self._compact_output(router_output),
                "text_to_sql": self._compact_output(text_to_sql_output),
                "sql_validator": self._compact_output(validator_output),
                "query_executor": self._compact_output(
                    executor_output,
                    omit_keys={"results"},
                ),
                "data_quality": self._compact_output(quality_output),
                "chart_agent": self._compact_output(chart_output),
            },
        }

    @staticmethod
    def _compact_output(
        output: dict[str, Any],
        omit_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        omit_keys = omit_keys or set()

        return {
            key: value
            for key, value in output.items()
            if key not in omit_keys
        }

    @staticmethod
    def _emergency_final_response(
        *,
        state: SupervisorWorkflowState,
        message: str,
        error_message: str | None,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "dataset_id": state["dataset_id"],
            "question": state["question"],
            "response_status": "failed",
            "response_type": "error_message",
            "message": message,
            "summary": None,
            "display_results": [],
            "display_result_count": 0,
            "display_columns": [],
            "chart_available": False,
            "chart_type": None,
            "chart_payload": None,
            "warnings": [],
            "recommendations": [],
            "technical_details": {
                "supervisor": {
                    "workflow_status": state.get("workflow_status"),
                    "failed_agent": state.get("failed_agent"),
                    "error_type": state.get("error_type"),
                    "error_message": error_message,
                    "blocking_reason": state.get("blocking_reason"),
                }
            },
            "error_type": "unexpected_formatting_error",
            "error_message": error_message,
            "blocking_reason": state.get("blocking_reason"),
            "metadata": {
                "agent": "SupervisorAgent",
                "emergency_response": True,
            },
        }


__all__ = [
    "SupervisorAgent",
    "SupervisorAgentInput",
    "SupervisorAgentOutput",
    "SupervisorWorkflowStatus",
    "SupervisorErrorType",
]