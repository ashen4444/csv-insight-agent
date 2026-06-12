from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.supervisor_agent import (
    SupervisorAgentInput,
    SupervisorAgentOutput,
    SupervisorErrorType,
    SupervisorWorkflowStatus,
)
from app.api.query import get_supervisor_agent
from app.main import app


class FakeSupervisorAgent:
    def __init__(
        self,
        output: SupervisorAgentOutput | None = None,
        exception: Exception | None = None,
    ) -> None:
        self.output = output
        self.exception = exception
        self.received_input: SupervisorAgentInput | None = None

    def run(
        self,
        agent_input: SupervisorAgentInput,
    ) -> SupervisorAgentOutput:
        self.received_input = agent_input

        if self.exception is not None:
            raise self.exception

        if self.output is None:
            raise RuntimeError("FakeSupervisorAgent output was not configured.")

        return self.output


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides.clear()

    test_client = TestClient(app)

    yield test_client

    app.dependency_overrides.clear()


def make_supervisor_output(
    *,
    dataset_id: str = "dataset-123",
    question: str = "What is the average salary?",
    success: bool = True,
    workflow_status: SupervisorWorkflowStatus = SupervisorWorkflowStatus.COMPLETED,
    response_status: str = "success",
    response_type: str = "table_answer",
    message: str = "Query completed successfully.",
    failed_agent: str | None = None,
    error_type: SupervisorErrorType | None = None,
    error_message: str | None = None,
    blocking_reason: str | None = None,
    final_response_overrides: dict[str, Any] | None = None,
) -> SupervisorAgentOutput:
    final_response = {
        "success": success,
        "dataset_id": dataset_id,
        "question": question,
        "response_status": response_status,
        "response_type": response_type,
        "message": message,
        "summary": "Test summary.",
        "display_results": [
            {
                "country": "USA",
                "average_salary": 120000,
            }
        ],
        "display_result_count": 1,
        "display_columns": ["country", "average_salary"],
        "chart_available": False,
        "chart_type": None,
        "chart_payload": None,
        "warnings": [],
        "recommendations": [],
        "technical_details": {},
        "error_type": error_type.value if error_type else None,
        "error_message": error_message,
        "blocking_reason": blocking_reason,
        "metadata": {
            "agent": "AnswerFormatterAgent",
        },
    }

    if final_response_overrides:
        final_response.update(final_response_overrides)

    return SupervisorAgentOutput(
        success=success,
        dataset_id=dataset_id,
        question=question,
        final_response=final_response,
        workflow_status=workflow_status,
        executed_agents=[
            "IntentRouterAgent",
            "AnswerFormatterAgent",
        ],
        skipped_agents=[],
        failed_agent=failed_agent,
        error_type=error_type,
        error_message=error_message,
        blocking_reason=blocking_reason,
        execution_time_ms=12.5,
        metadata={
            "agent": "SupervisorAgent",
            "workflow_status": workflow_status.value,
        },
    )


def override_supervisor(fake_supervisor: FakeSupervisorAgent) -> None:
    app.dependency_overrides[get_supervisor_agent] = lambda: fake_supervisor


def test_query_endpoint_calls_supervisor_and_returns_success_response(
    client: TestClient,
) -> None:
    output = make_supervisor_output()
    fake_supervisor = FakeSupervisorAgent(output=output)
    override_supervisor(fake_supervisor)

    response = client.post(
        "/api/query",
        json={
            "dataset_id": "dataset-123",
            "question": "What is the average salary?",
            "request_id": "req-001",
            "chart_generation_approved": True,
            "approved_chart_type": "bar_chart",
            "metadata": {
                "source": "pytest",
            },
        },
    )

    assert response.status_code == 200

    response_body = response.json()

    assert response_body["success"] is True
    assert response_body["dataset_id"] == "dataset-123"
    assert response_body["question"] == "What is the average salary?"
    assert response_body["workflow_status"] == "completed"
    assert response_body["final_response"]["message"] == (
        "Query completed successfully."
    )

    assert isinstance(fake_supervisor.received_input, SupervisorAgentInput)
    assert fake_supervisor.received_input.dataset_id == "dataset-123"
    assert fake_supervisor.received_input.question == (
        "What is the average salary?"
    )
    assert fake_supervisor.received_input.request_id == "req-001"
    assert fake_supervisor.received_input.chart_generation_approved is True
    assert fake_supervisor.received_input.approved_chart_type == "bar_chart"
    assert fake_supervisor.received_input.metadata == {
        "source": "pytest",
    }


def test_query_endpoint_returns_formatted_unsupported_response(
    client: TestClient,
) -> None:
    output = make_supervisor_output(
        success=False,
        workflow_status=SupervisorWorkflowStatus.BLOCKED,
        response_status="blocked",
        response_type="unsupported_request",
        message="This request is outside the supported CSV analysis scope.",
        failed_agent=None,
        error_type=None,
        blocking_reason="non_csv_task",
        final_response_overrides={
            "summary": None,
            "display_results": [],
            "display_result_count": 0,
            "display_columns": [],
            "blocking_reason": "non_csv_task",
        },
    )
    fake_supervisor = FakeSupervisorAgent(output=output)
    override_supervisor(fake_supervisor)

    response = client.post(
        "/api/query",
        json={
            "dataset_id": "dataset-123",
            "question": "Write me a poem about cats.",
        },
    )

    assert response.status_code == 200

    response_body = response.json()

    assert response_body["success"] is False
    assert response_body["workflow_status"] == "blocked"
    assert response_body["blocking_reason"] == "non_csv_task"
    assert response_body["final_response"]["response_type"] == (
        "unsupported_request"
    )
    assert response_body["final_response"]["message"] == (
        "This request is outside the supported CSV analysis scope."
    )


def test_query_endpoint_preserves_clarification_response(
    client: TestClient,
) -> None:
    output = make_supervisor_output(
        success=False,
        workflow_status=SupervisorWorkflowStatus.BLOCKED,
        response_status="needs_clarification",
        response_type="clarification_question",
        message="Which column should I use for this analysis?",
        blocking_reason="Which column should I use for this analysis?",
        final_response_overrides={
            "summary": None,
            "display_results": [],
            "display_result_count": 0,
            "display_columns": [],
            "blocking_reason": "Which column should I use for this analysis?",
        },
    )
    fake_supervisor = FakeSupervisorAgent(output=output)
    override_supervisor(fake_supervisor)

    response = client.post(
        "/api/query",
        json={
            "dataset_id": "dataset-123",
            "question": "Compare the values.",
        },
    )

    assert response.status_code == 200

    response_body = response.json()

    assert response_body["success"] is False
    assert response_body["workflow_status"] == "blocked"
    assert response_body["final_response"]["response_status"] == (
        "needs_clarification"
    )
    assert response_body["final_response"]["response_type"] == (
        "clarification_question"
    )
    assert response_body["final_response"]["message"] == (
        "Which column should I use for this analysis?"
    )


def test_query_endpoint_returns_safe_response_when_supervisor_raises(
    client: TestClient,
) -> None:
    fake_supervisor = FakeSupervisorAgent(
        exception=RuntimeError("Supervisor exploded.")
    )
    override_supervisor(fake_supervisor)

    response = client.post(
        "/api/query",
        json={
            "dataset_id": "dataset-123",
            "question": "What is the average salary?",
        },
    )

    assert response.status_code == 500

    response_body = response.json()

    assert response_body["success"] is False
    assert response_body["workflow_status"] == "failed"
    assert response_body["failed_agent"] == "SupervisorAgent"
    assert response_body["error_type"] == "unexpected_supervisor_api_error"
    assert response_body["final_response"]["success"] is False
    assert response_body["final_response"]["response_type"] == "error_message"
    assert response_body["final_response"]["chart_available"] is False


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "schema_context",
        "schema_profile",
        "schema_context_override",
        "table_name",
        "allowed_columns",
    ],
)
def test_query_endpoint_rejects_trusted_schema_metadata_from_request_body(
    client: TestClient,
    forbidden_field: str,
) -> None:
    fake_supervisor = FakeSupervisorAgent(output=make_supervisor_output())
    override_supervisor(fake_supervisor)

    response = client.post(
        "/api/query",
        json={
            "dataset_id": "dataset-123",
            "question": "What is the average salary?",
            forbidden_field: {
                "malicious": "caller-provided trusted metadata",
            },
        },
    )

    assert response.status_code == 422
    assert fake_supervisor.received_input is None


def test_query_endpoint_does_not_forward_trusted_schema_metadata(
    client: TestClient,
) -> None:
    fake_supervisor = FakeSupervisorAgent(output=make_supervisor_output())
    override_supervisor(fake_supervisor)

    response = client.post(
        "/api/query",
        json={
            "dataset_id": "dataset-123",
            "question": "What is the average salary?",
            "metadata": {
                "client_request_source": "pytest",
            },
        },
    )

    assert response.status_code == 200

    assert isinstance(fake_supervisor.received_input, SupervisorAgentInput)
    assert not hasattr(fake_supervisor.received_input, "schema_context")
    assert not hasattr(fake_supervisor.received_input, "schema_profile")
    assert not hasattr(fake_supervisor.received_input, "schema_context_override")
    assert not hasattr(fake_supervisor.received_input, "table_name")
    assert not hasattr(fake_supervisor.received_input, "allowed_columns")