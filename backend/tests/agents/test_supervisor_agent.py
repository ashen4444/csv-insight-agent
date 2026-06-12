# backend/tests/agents/test_supervisor_agent.py

from __future__ import annotations

from typing import Any

import pytest

from app.agents.answer_formatter_agent import (
    AnswerFormatterAgent,
    AnswerFormatterAgentOutput,
    AnswerResponseStatus,
    AnswerResponseType,
)
from app.agents.chart_agent import (
    ChartAgentErrorType,
    ChartAgentOutput,
    ChartGenerationStatus,
)
from app.agents.data_quality_agent import (
    DataQualityAgentOutput,
    DataQualityStatus,
)
from app.agents.intent_router.models import (
    IntentRouterResult,
    QueryIntent,
    RouterDecisionSource,
    RoutingCapability,
)
from app.agents.query_executor_agent import (
    QueryExecutionStatus,
    QueryExecutorAgentOutput,
    QueryExecutorErrorType,
)
from app.agents.sql_validator_agent import (
    SQLValidationErrorType,
    SQLValidationStatus,
    SQLValidatorAgentOutput,
    SQLValidatorSchemaContextSource,
)
from app.agents.supervisor_agent import (
    SupervisorAgent,
    SupervisorWorkflowStatus,
)
from app.agents.text_to_sql_agent import (
    SchemaContextSource,
    TextToSQLAgentOutput,
    TextToSQLErrorType,
)


DATASET_ID = "dataset_123"
QUESTION = "Average salary by country"
SQL = 'SELECT "Country", AVG("Salary") AS "avg_salary" FROM table GROUP BY "Country"'
RESULTS = [{"Country": "Sri Lanka", "avg_salary": 100000.0}]


class FakeIntentRouter:
    def __init__(self, output: IntentRouterResult) -> None:
        self.output = output
        self.calls = 0

    def classify(self, question: str) -> IntentRouterResult:
        self.calls += 1
        return self.output


class FakeTextToSQLAgent:
    def __init__(self, output: TextToSQLAgentOutput) -> None:
        self.output = output
        self.calls = 0
        self.last_input = None

    def generate(self, agent_input: Any) -> TextToSQLAgentOutput:
        self.calls += 1
        self.last_input = agent_input
        return self.output


class FakeSQLValidatorAgent:
    def __init__(self, output: SQLValidatorAgentOutput) -> None:
        self.output = output
        self.calls = 0
        self.last_input = None

    def validate(self, agent_input: Any) -> SQLValidatorAgentOutput:
        self.calls += 1
        self.last_input = agent_input
        return self.output


class FakeQueryExecutorAgent:
    def __init__(self, output: QueryExecutorAgentOutput) -> None:
        self.output = output
        self.calls = 0
        self.last_input = None

    def execute(self, agent_input: Any) -> QueryExecutorAgentOutput:
        self.calls += 1
        self.last_input = agent_input
        return self.output


class FakeDataQualityAgent:
    def __init__(self, output: DataQualityAgentOutput) -> None:
        self.output = output
        self.calls = 0
        self.last_input = None

    def evaluate(self, agent_input: Any) -> DataQualityAgentOutput:
        self.calls += 1
        self.last_input = agent_input
        return self.output


class FakeChartAgent:
    def __init__(self, output: ChartAgentOutput) -> None:
        self.output = output
        self.calls = 0
        self.last_input = None

    def generate(self, agent_input: Any) -> ChartAgentOutput:
        self.calls += 1
        self.last_input = agent_input
        return self.output


class ExplodingAgent:
    def __getattr__(self, name: str) -> Any:
        def _raise(*args: Any, **kwargs: Any) -> None:
            raise AssertionError(f"Unexpected downstream call: {name}")

        return _raise


class CapturingAnswerFormatter:
    def __init__(self) -> None:
        self.calls = 0
        self.last_input = None

    def format(self, agent_input: Any) -> AnswerFormatterAgentOutput:
        self.calls += 1
        self.last_input = agent_input

        return AnswerFormatterAgentOutput(
            success=True,
            dataset_id=agent_input.dataset_id,
            question=agent_input.question,
            response_status=AnswerResponseStatus.READY,
            response_type=AnswerResponseType.TEXT_WITH_TABLE,
            message="Captured formatter input.",
            summary="Captured.",
            display_results=agent_input.results,
            display_result_count=len(agent_input.results),
            display_columns=["Country", "avg_salary"],
            chart_available=False,
            chart_type=None,
            chart_payload=None,
            warnings=[],
            recommendations=[],
            technical_details={},
            error_type=None,
            error_message=None,
            blocking_reason=None,
            metadata={},
        )


def analytics_intent() -> IntentRouterResult:
    return IntentRouterResult(
        primary_intent=QueryIntent.ANALYTICS_QUERY,
        required_capabilities=[
            RoutingCapability.SQL_GENERATION,
            RoutingCapability.SQL_VALIDATION,
            RoutingCapability.QUERY_EXECUTION,
            RoutingCapability.RESULT_ANALYSIS,
            RoutingCapability.ANSWER_FORMATTING,
        ],
        confidence=0.95,
        reason="Analytics query detected.",
        source=RouterDecisionSource.RULE_BASED,
        matched_signals=["average"],
        normalized_question=QUESTION.lower(),
    )


def visualization_intent() -> IntentRouterResult:
    return IntentRouterResult(
        primary_intent=QueryIntent.VISUALIZATION_QUERY,
        required_capabilities=[
            RoutingCapability.SQL_GENERATION,
            RoutingCapability.SQL_VALIDATION,
            RoutingCapability.QUERY_EXECUTION,
            RoutingCapability.RESULT_ANALYSIS,
            RoutingCapability.CHART_SELECTION,
            RoutingCapability.CHART_PAYLOAD_GENERATION,
            RoutingCapability.CHART_VALIDATION,
            RoutingCapability.ANSWER_FORMATTING,
        ],
        confidence=0.95,
        reason="Visualization query detected.",
        source=RouterDecisionSource.RULE_BASED,
        matched_signals=["chart"],
        normalized_question="visualize average salary by country",
    )


def unsupported_intent() -> IntentRouterResult:
    return IntentRouterResult(
        primary_intent=QueryIntent.UNSUPPORTED_QUERY,
        required_capabilities=[
            RoutingCapability.UNSUPPORTED_RESPONSE,
            RoutingCapability.ANSWER_FORMATTING,
        ],
        confidence=0.99,
        reason="Request is outside CSV analysis scope.",
        source=RouterDecisionSource.RULE_BASED,
        matched_signals=["weather"],
        normalized_question="what is the weather?",
        is_routable=False,
        blocking_reason="Unsupported non-CSV task.",
        unsupported_reason="non_csv_task",
    )


def clarification_intent() -> IntentRouterResult:
    return IntentRouterResult(
        primary_intent=QueryIntent.ANALYTICS_QUERY,
        required_capabilities=[
            RoutingCapability.SQL_GENERATION,
            RoutingCapability.ANSWER_FORMATTING,
        ],
        confidence=0.45,
        reason="Question is ambiguous.",
        source=RouterDecisionSource.LLM,
        matched_signals=[],
        normalized_question="compare them",
        needs_clarification=True,
        clarification_question="Which columns do you want to compare?",
        is_routable=True,
    )


def schema_intent() -> IntentRouterResult:
    return IntentRouterResult(
        primary_intent=QueryIntent.SCHEMA_QUESTION,
        required_capabilities=[
            RoutingCapability.SCHEMA_PROFILING,
            RoutingCapability.ANSWER_FORMATTING,
        ],
        confidence=0.95,
        reason="Schema question detected.",
        source=RouterDecisionSource.RULE_BASED,
        matched_signals=["columns"],
        normalized_question="what columns are in this dataset?",
    )


def text_to_sql_success() -> TextToSQLAgentOutput:
    return TextToSQLAgentOutput(
        success=True,
        dataset_id=DATASET_ID,
        question=QUESTION,
        sql=SQL,
        model_required=True,
        schema_context_source=SchemaContextSource.RESOLVED_FROM_DATASET_ID,
        error_type=None,
        error_message=None,
        execution_time_ms=12.5,
        metadata={"agent": "TextToSQLAgent"},
    )


def text_to_sql_failure() -> TextToSQLAgentOutput:
    return TextToSQLAgentOutput(
        success=False,
        dataset_id=DATASET_ID,
        question=QUESTION,
        sql=None,
        model_required=True,
        schema_context_source=None,
        error_type=TextToSQLErrorType.SQL_GENERATION_FAILED,
        error_message="LLM SQL generation failed.",
        execution_time_ms=5.0,
        metadata={"agent": "TextToSQLAgent"},
    )


def validation_success() -> SQLValidatorAgentOutput:
    return SQLValidatorAgentOutput(
        success=True,
        dataset_id=DATASET_ID,
        question=QUESTION,
        sql=SQL,
        validation_status=SQLValidationStatus.VALID,
        is_valid=True,
        is_safe_to_execute=True,
        schema_context_source=SQLValidatorSchemaContextSource.BUILT_FROM_DATASET_ID,
        error_type=None,
        error_message=None,
        blocking_reason=None,
        execution_time_ms=2.0,
        metadata={"agent": "SQLValidatorAgent"},
    )


def validation_blocked() -> SQLValidatorAgentOutput:
    return SQLValidatorAgentOutput(
        success=False,
        dataset_id=DATASET_ID,
        question=QUESTION,
        sql="DROP TABLE table",
        validation_status=SQLValidationStatus.BLOCKED,
        is_valid=False,
        is_safe_to_execute=False,
        schema_context_source=SQLValidatorSchemaContextSource.BUILT_FROM_DATASET_ID,
        error_type=SQLValidationErrorType.SQL_VALIDATION_FAILED,
        error_message="Only SELECT queries are allowed.",
        blocking_reason="Only SELECT queries are allowed.",
        execution_time_ms=2.0,
        metadata={"agent": "SQLValidatorAgent"},
    )


def execution_success() -> QueryExecutorAgentOutput:
    return QueryExecutorAgentOutput(
        success=True,
        dataset_id=DATASET_ID,
        question=QUESTION,
        sql=SQL,
        executed=True,
        execution_status=QueryExecutionStatus.SUCCEEDED,
        results=RESULTS,
        row_count=1,
        execution_time_ms=8.0,
        error_type=None,
        error_message=None,
        blocking_reason=None,
        metadata={"agent": "QueryExecutorAgent"},
    )


def execution_failed() -> QueryExecutorAgentOutput:
    return QueryExecutorAgentOutput(
        success=False,
        dataset_id=DATASET_ID,
        question=QUESTION,
        sql=SQL,
        executed=False,
        execution_status=QueryExecutionStatus.FAILED,
        results=[],
        row_count=0,
        execution_time_ms=3.0,
        error_type=QueryExecutorErrorType.QUERY_EXECUTION_FAILED,
        error_message="DuckDB execution failed.",
        blocking_reason="Query execution failed in the execution service.",
        metadata={"agent": "QueryExecutorAgent"},
    )


def quality_success() -> DataQualityAgentOutput:
    return DataQualityAgentOutput(
        success=True,
        dataset_id=DATASET_ID,
        question=QUESTION,
        sql=SQL,
        quality_status=DataQualityStatus.PASSED,
        is_result_usable=True,
        is_result_empty=False,
        is_result_too_large=False,
        has_null_warnings=False,
        has_duplicate_warnings=False,
        has_visualization_warnings=False,
        row_count=1,
        execution_time_ms=8.0,
        warnings=[],
        recommendations=[],
        error_type=None,
        error_message=None,
        blocking_reason=None,
        metadata={"agent": "DataQualityAgent"},
    )


def quality_blocked() -> DataQualityAgentOutput:
    return DataQualityAgentOutput(
        success=False,
        dataset_id=DATASET_ID,
        question=QUESTION,
        sql=SQL,
        quality_status=DataQualityStatus.FAILED,
        is_result_usable=False,
        is_result_empty=False,
        is_result_too_large=False,
        has_null_warnings=False,
        has_duplicate_warnings=False,
        has_visualization_warnings=False,
        row_count=1,
        execution_time_ms=8.0,
        warnings=[],
        recommendations=[],
        error_type=None,
        error_message="Result is not safe to present.",
        blocking_reason="Data quality checks failed.",
        metadata={"agent": "DataQualityAgent"},
    )


def chart_not_requested() -> ChartAgentOutput:
    return ChartAgentOutput(
        success=True,
        dataset_id=DATASET_ID,
        question=QUESTION,
        sql=SQL,
        chart_generation_status=ChartGenerationStatus.NOT_REQUESTED,
        chart_generation_enabled=False,
        chart_type=None,
        selected_chart_type=None,
        requested_chart_type=None,
        recommended_chart_type="bar_chart",
        chart_source=None,
        chart_payload=None,
        chart_warning=None,
        chart_warnings=[],
        is_chart_available=False,
        is_chart_recommended=True,
        visualization_intent={
            "visualization_requested": False,
            "requested_chart_type": None,
        },
        result_analysis={
            "result_type": "aggregated_table",
            "recommended_visualization": "bar_chart",
            "is_visualizable": True,
            "x_axis": "Country",
            "y_axis": "avg_salary",
            "confidence": 0.9,
            "reason": "Categorical comparison.",
        },
        chart_selection={
            "chart_generation_enabled": False,
            "final_chart_type": None,
            "chart_source": None,
        },
        error_type=None,
        error_message=None,
        blocking_reason=None,
        metadata={"agent": "ChartAgent"},
    )


def chart_generated() -> ChartAgentOutput:
    return ChartAgentOutput(
        success=True,
        dataset_id=DATASET_ID,
        question=QUESTION,
        sql=SQL,
        chart_generation_status=ChartGenerationStatus.GENERATED,
        chart_generation_enabled=True,
        chart_type="bar_chart",
        selected_chart_type="bar_chart",
        requested_chart_type=None,
        recommended_chart_type="bar_chart",
        chart_source="result_analysis",
        chart_payload={
            "chart_type": "bar_chart",
            "x": ["Sri Lanka"],
            "y": [100000.0],
        },
        chart_warning=None,
        chart_warnings=[],
        is_chart_available=True,
        is_chart_recommended=True,
        visualization_intent={
            "visualization_requested": True,
            "requested_chart_type": None,
        },
        result_analysis={
            "result_type": "aggregated_table",
            "recommended_visualization": "bar_chart",
            "is_visualizable": True,
            "x_axis": "Country",
            "y_axis": "avg_salary",
            "confidence": 0.9,
            "reason": "Categorical comparison.",
        },
        chart_selection={
            "chart_generation_enabled": True,
            "final_chart_type": "bar_chart",
            "chart_source": "result_analysis",
        },
        error_type=None,
        error_message=None,
        blocking_reason=None,
        metadata={"agent": "ChartAgent"},
    )


def chart_unavailable() -> ChartAgentOutput:
    return ChartAgentOutput(
        success=False,
        dataset_id=DATASET_ID,
        question=QUESTION,
        sql=SQL,
        chart_generation_status=ChartGenerationStatus.UNAVAILABLE,
        chart_generation_enabled=True,
        chart_type=None,
        selected_chart_type="metric_card",
        requested_chart_type="metric_card",
        recommended_chart_type="metric_card",
        chart_source="user_request",
        chart_payload=None,
        chart_warning={
            "warning_type": "chart_payload_unavailable",
            "severity": "warning",
            "message": "Payload builder does not support metric_card yet.",
            "source": "chart_agent",
            "recommendation": "Return table result with chart warning.",
            "metadata": {},
        },
        chart_warnings=[],
        is_chart_available=False,
        is_chart_recommended=True,
        visualization_intent={
            "visualization_requested": True,
            "requested_chart_type": "metric_card",
        },
        result_analysis={
            "result_type": "single_metric",
            "recommended_visualization": "metric_card",
            "is_visualizable": True,
            "x_axis": None,
            "y_axis": "avg_salary",
            "confidence": 0.9,
            "reason": "Single metric.",
        },
        chart_selection={
            "chart_generation_enabled": True,
            "final_chart_type": "metric_card",
            "chart_source": "user_request",
        },
        error_type=ChartAgentErrorType.CHART_PAYLOAD_UNAVAILABLE,
        error_message="Payload builder does not support metric_card yet.",
        blocking_reason="Selected chart type is unsupported.",
        metadata={"agent": "ChartAgent"},
    )


def build_supervisor(
    *,
    intent: IntentRouterResult | None = None,
    text_output: TextToSQLAgentOutput | None = None,
    validator_output: SQLValidatorAgentOutput | None = None,
    executor_output: QueryExecutorAgentOutput | None = None,
    quality_output: DataQualityAgentOutput | None = None,
    chart_output: ChartAgentOutput | None = None,
    answer_formatter: Any | None = None,
) -> SupervisorAgent:
    return SupervisorAgent(
        intent_router=FakeIntentRouter(intent or analytics_intent()),
        text_to_sql_agent=(
            FakeTextToSQLAgent(text_output or text_to_sql_success())
            if text_output is not None
            else FakeTextToSQLAgent(text_to_sql_success())
        ),
        sql_validator_agent=(
            FakeSQLValidatorAgent(validator_output or validation_success())
            if validator_output is not None
            else FakeSQLValidatorAgent(validation_success())
        ),
        query_executor_agent=(
            FakeQueryExecutorAgent(executor_output or execution_success())
            if executor_output is not None
            else FakeQueryExecutorAgent(execution_success())
        ),
        data_quality_agent=(
            FakeDataQualityAgent(quality_output or quality_success())
            if quality_output is not None
            else FakeDataQualityAgent(quality_success())
        ),
        chart_agent=(
            FakeChartAgent(chart_output or chart_not_requested())
            if chart_output is not None
            else FakeChartAgent(chart_not_requested())
        ),
        answer_formatter_agent=answer_formatter or AnswerFormatterAgent(),
    )


def test_successful_analytics_workflow_formats_table_answer() -> None:
    supervisor = build_supervisor()

    output = supervisor.run(
        {
            "dataset_id": DATASET_ID,
            "question": QUESTION,
            "request_id": "req_1",
        }
    )

    assert output.success is True
    assert output.workflow_status == SupervisorWorkflowStatus.COMPLETED
    assert output.final_response["response_status"] == "answer_ready"
    assert output.final_response["response_type"] == "text_with_table"
    assert output.final_response["display_results"] == RESULTS
    assert output.final_response["chart_available"] is False
    assert output.executed_agents == [
        "IntentRouterAgent",
        "TextToSQLAgent",
        "SQLValidatorAgent",
        "QueryExecutorAgent",
        "DataQualityAgent",
        "ChartAgent",
        "AnswerFormatterAgent",
    ]
    assert output.skipped_agents == []


def test_successful_visualization_workflow_returns_chart_payload() -> None:
    supervisor = build_supervisor(
        intent=visualization_intent(),
        chart_output=chart_generated(),
    )

    output = supervisor.run(
        {
            "dataset_id": DATASET_ID,
            "question": "Visualize average salary by country",
            "request_id": "req_2",
        }
    )

    assert output.success is True
    assert output.workflow_status == SupervisorWorkflowStatus.COMPLETED
    assert output.final_response["chart_available"] is True
    assert output.final_response["chart_type"] == "bar_chart"
    assert output.final_response["chart_payload"]["chart_type"] == "bar_chart"
    assert output.final_response["response_type"] == "text_with_table_and_chart"


def test_unsupported_query_stops_after_router_and_formatter() -> None:
    supervisor = SupervisorAgent(
        intent_router=FakeIntentRouter(unsupported_intent()),
        text_to_sql_agent=ExplodingAgent(),
        sql_validator_agent=ExplodingAgent(),
        query_executor_agent=ExplodingAgent(),
        data_quality_agent=ExplodingAgent(),
        chart_agent=ExplodingAgent(),
        answer_formatter_agent=AnswerFormatterAgent(),
    )

    output = supervisor.run(
        {
            "dataset_id": DATASET_ID,
            "question": "What is the weather?",
        }
    )

    assert output.success is False
    assert output.workflow_status == SupervisorWorkflowStatus.BLOCKED
    assert output.final_response["response_status"] == "unsupported"
    assert output.final_response["error_type"] == "unsupported_query"
    assert output.executed_agents == [
        "IntentRouterAgent",
        "AnswerFormatterAgent",
    ]
    assert "TextToSQLAgent" in output.skipped_agents


def test_needs_clarification_stops_after_router_and_formatter() -> None:
    supervisor = SupervisorAgent(
        intent_router=FakeIntentRouter(clarification_intent()),
        text_to_sql_agent=ExplodingAgent(),
        sql_validator_agent=ExplodingAgent(),
        query_executor_agent=ExplodingAgent(),
        data_quality_agent=ExplodingAgent(),
        chart_agent=ExplodingAgent(),
        answer_formatter_agent=AnswerFormatterAgent(),
    )

    output = supervisor.run(
        {
            "dataset_id": DATASET_ID,
            "question": "Compare them",
        }
    )

    assert output.success is False
    assert output.workflow_status == SupervisorWorkflowStatus.BLOCKED
    assert output.final_response["response_status"] == "needs_clarification"
    assert output.final_response["message"] == "Which columns do you want to compare?"
    assert output.executed_agents == [
        "IntentRouterAgent",
        "AnswerFormatterAgent",
    ]


def test_schema_question_returns_clean_routing_block_until_formatter_is_extended() -> None:
    supervisor = SupervisorAgent(
        intent_router=FakeIntentRouter(schema_intent()),
        text_to_sql_agent=ExplodingAgent(),
        sql_validator_agent=ExplodingAgent(),
        query_executor_agent=ExplodingAgent(),
        data_quality_agent=ExplodingAgent(),
        chart_agent=ExplodingAgent(),
        answer_formatter_agent=AnswerFormatterAgent(),
    )

    output = supervisor.run(
        {
            "dataset_id": DATASET_ID,
            "question": "What columns are in this dataset?",
        }
    )

    assert output.success is False
    assert output.workflow_status == SupervisorWorkflowStatus.BLOCKED
    assert output.error_type == "unsupported_workflow_path"
    assert output.final_response["response_status"] == "blocked"
    assert "Supervisor v1 does not yet support" in output.final_response["message"]


def test_text_to_sql_failure_stops_validation_and_execution() -> None:
    validator = ExplodingAgent()
    executor = ExplodingAgent()

    supervisor = SupervisorAgent(
        intent_router=FakeIntentRouter(analytics_intent()),
        text_to_sql_agent=FakeTextToSQLAgent(text_to_sql_failure()),
        sql_validator_agent=validator,
        query_executor_agent=executor,
        data_quality_agent=ExplodingAgent(),
        chart_agent=ExplodingAgent(),
        answer_formatter_agent=AnswerFormatterAgent(),
    )

    output = supervisor.run(
        {
            "dataset_id": DATASET_ID,
            "question": QUESTION,
        }
    )

    assert output.success is False
    assert output.workflow_status == SupervisorWorkflowStatus.FAILED
    assert output.failed_agent == "TextToSQLAgent"
    assert output.final_response["error_type"] == "sql_generation_failed"
    assert output.final_response["blocking_reason"] == (
        "The system could not generate SQL for this question."
    )
    assert output.final_response["message"] == "LLM SQL generation failed."


def test_sql_validation_blocked_stops_execution() -> None:
    supervisor = SupervisorAgent(
        intent_router=FakeIntentRouter(analytics_intent()),
        text_to_sql_agent=FakeTextToSQLAgent(text_to_sql_success()),
        sql_validator_agent=FakeSQLValidatorAgent(validation_blocked()),
        query_executor_agent=ExplodingAgent(),
        data_quality_agent=ExplodingAgent(),
        chart_agent=ExplodingAgent(),
        answer_formatter_agent=AnswerFormatterAgent(),
    )

    output = supervisor.run(
        {
            "dataset_id": DATASET_ID,
            "question": QUESTION,
        }
    )

    assert output.success is False
    assert output.workflow_status == SupervisorWorkflowStatus.BLOCKED
    assert output.failed_agent == "SQLValidatorAgent"
    assert output.final_response["error_type"] == "sql_validation_blocked"
    assert "Only SELECT queries are allowed" in output.final_response["message"]


def test_query_execution_failure_stops_data_quality_and_chart() -> None:
    supervisor = SupervisorAgent(
        intent_router=FakeIntentRouter(analytics_intent()),
        text_to_sql_agent=FakeTextToSQLAgent(text_to_sql_success()),
        sql_validator_agent=FakeSQLValidatorAgent(validation_success()),
        query_executor_agent=FakeQueryExecutorAgent(execution_failed()),
        data_quality_agent=ExplodingAgent(),
        chart_agent=ExplodingAgent(),
        answer_formatter_agent=AnswerFormatterAgent(),
    )

    output = supervisor.run(
        {
            "dataset_id": DATASET_ID,
            "question": QUESTION,
        }
    )

    assert output.success is False
    assert output.workflow_status == SupervisorWorkflowStatus.FAILED
    assert output.failed_agent == "QueryExecutorAgent"
    assert output.final_response["error_type"] == "execution_failed"
    assert "Query execution failed" in output.final_response["message"]


def test_data_quality_blocked_prevents_chart_generation() -> None:
    supervisor = SupervisorAgent(
        intent_router=FakeIntentRouter(analytics_intent()),
        text_to_sql_agent=FakeTextToSQLAgent(text_to_sql_success()),
        sql_validator_agent=FakeSQLValidatorAgent(validation_success()),
        query_executor_agent=FakeQueryExecutorAgent(execution_success()),
        data_quality_agent=FakeDataQualityAgent(quality_blocked()),
        chart_agent=ExplodingAgent(),
        answer_formatter_agent=AnswerFormatterAgent(),
    )

    output = supervisor.run(
        {
            "dataset_id": DATASET_ID,
            "question": QUESTION,
        }
    )

    assert output.success is False
    assert output.workflow_status == SupervisorWorkflowStatus.BLOCKED
    assert output.failed_agent == "DataQualityAgent"
    assert output.final_response["error_type"] == "data_quality_blocked"
    assert "data quality checks did not pass" in output.final_response["message"].lower()
    assert "ChartAgent" in output.skipped_agents


def test_chart_unavailable_still_returns_table_answer_with_warning() -> None:
    supervisor = build_supervisor(chart_output=chart_unavailable())

    output = supervisor.run(
        {
            "dataset_id": DATASET_ID,
            "question": "Show average salary as a metric card",
        }
    )

    assert output.success is True
    assert output.workflow_status == SupervisorWorkflowStatus.COMPLETED
    assert output.final_response["response_status"] == "answer_ready_with_warning"
    assert output.final_response["chart_available"] is False
    assert output.final_response["display_results"] == RESULTS

    warning_types = {
        warning["warning_type"]
        for warning in output.final_response["warnings"]
    }
    assert "chart_unavailable" in warning_types


def test_answer_formatter_input_mapping_is_correct() -> None:
    formatter = CapturingAnswerFormatter()
    supervisor = build_supervisor(answer_formatter=formatter)

    output = supervisor.run(
        {
            "dataset_id": DATASET_ID,
            "question": QUESTION,
            "request_id": "req_mapping",
        }
    )

    assert output.success is True
    assert formatter.calls == 1

    formatter_input = formatter.last_input
    assert formatter_input.dataset_id == DATASET_ID
    assert formatter_input.question == QUESTION
    assert formatter_input.request_id == "req_mapping"

    assert formatter_input.primary_intent == "analytics_query"
    assert formatter_input.sql_generation_success is True
    assert formatter_input.validation_success is True
    assert formatter_input.validation_status == "valid"
    assert formatter_input.is_safe_to_execute is True

    assert formatter_input.execution_success is True
    assert formatter_input.execution_status == "execution_succeeded"
    assert formatter_input.executed is True
    assert formatter_input.results == RESULTS
    assert formatter_input.row_count == 1

    assert formatter_input.data_quality_success is True
    assert formatter_input.quality_status == "quality_passed"
    assert formatter_input.is_result_usable is True

    assert formatter_input.chart_success is True
    assert formatter_input.chart_generation_status == "chart_not_requested"
    assert formatter_input.is_chart_recommended is True

    dumped_input = formatter_input.model_dump(mode="json")
    assert "schema_context" not in dumped_input
    assert "schema_profile" not in dumped_input
    assert "table_name" not in dumped_input
    assert "allowed_columns" not in dumped_input


def test_supervisor_output_to_dict_is_frontend_friendly() -> None:
    supervisor = build_supervisor()

    output = supervisor.run(
        {
            "dataset_id": DATASET_ID,
            "question": QUESTION,
        }
    )

    serialized = output.to_dict()

    assert serialized["success"] is True
    assert serialized["workflow_status"] == "completed"
    assert isinstance(serialized["final_response"], dict)
    assert isinstance(serialized["executed_agents"], list)
    assert isinstance(serialized["skipped_agents"], list)
    assert isinstance(serialized["metadata"], dict)