from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agents.supervisor_agent import (
    SupervisorAgent,
    SupervisorAgentInput,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/query", tags=["Query"])


class QueryRequest(BaseModel):
    """
    Public API request model for dataset questions.

    Important:
    - Do not accept trusted schema metadata from API callers.
    - Trusted schema context must be resolved internally by downstream agents
      using dataset_id.
    """

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)

    request_id: str | None = None

    chart_generation_approved: bool = False
    approved_chart_type: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


@lru_cache(maxsize=1)
def _get_supervisor_agent_singleton() -> SupervisorAgent:
    return SupervisorAgent()


def get_supervisor_agent() -> SupervisorAgent:
    """
    FastAPI dependency boundary for SupervisorAgent.

    This keeps the endpoint thin and makes API tests easy to isolate by
    overriding this dependency with a fake Supervisor.
    """

    try:
        return _get_supervisor_agent_singleton()
    except RuntimeError as exc:
        logger.exception("SupervisorAgent is unavailable.")

        raise HTTPException(
            status_code=503,
            detail={
                "success": False,
                "error_type": "supervisor_unavailable",
                "message": "Supervisor Agent is unavailable.",
                "details": str(exc),
            },
        ) from exc


@router.post("")
def ask_dataset_question(
    request: QueryRequest,
    supervisor_agent: SupervisorAgent = Depends(get_supervisor_agent),
) -> Any:
    """
    Delegate query orchestration to SupervisorAgent.

    The endpoint intentionally does not:
    - build schema context,
    - generate SQL,
    - validate SQL,
    - execute SQL,
    - build chart payloads,
    - accept trusted schema metadata from the caller.
    """

    supervisor_input = SupervisorAgentInput(
        dataset_id=request.dataset_id,
        question=request.question,
        request_id=request.request_id,
        chart_generation_approved=request.chart_generation_approved,
        approved_chart_type=request.approved_chart_type,
        metadata=request.metadata,
    )

    try:
        supervisor_output = supervisor_agent.run(supervisor_input)
    except Exception as exc:
        logger.exception("Unexpected failure while running SupervisorAgent.")

        return JSONResponse(
            status_code=500,
            content=_build_unexpected_supervisor_failure_response(
                request=request,
                error_message=str(exc),
            ),
        )

    return supervisor_output.to_dict()


def _build_unexpected_supervisor_failure_response(
    *,
    request: QueryRequest,
    error_message: str,
) -> dict[str, Any]:
    return {
        "success": False,
        "dataset_id": request.dataset_id,
        "question": request.question,
        "final_response": {
            "success": False,
            "dataset_id": request.dataset_id,
            "question": request.question,
            "response_status": "failed",
            "response_type": "error_message",
            "message": (
                "The query workflow failed unexpectedly before the "
                "Supervisor Agent could return a response."
            ),
            "summary": None,
            "display_results": [],
            "display_result_count": 0,
            "display_columns": [],
            "chart_available": False,
            "chart_type": None,
            "chart_payload": None,
            "warnings": [],
            "recommendations": [
                "Check backend logs for the Supervisor Agent failure details."
            ],
            "technical_details": {
                "api": {
                    "error_type": "unexpected_supervisor_api_error",
                    "error_message": error_message,
                }
            },
            "error_type": "unexpected_supervisor_api_error",
            "error_message": (
                "Supervisor Agent execution failed before a structured "
                "SupervisorAgentOutput was returned."
            ),
            "blocking_reason": "The API could not complete query orchestration.",
            "metadata": {
                "agent": "FastAPIQueryEndpoint",
                "safe_fallback_response": True,
            },
        },
        "workflow_status": "failed",
        "executed_agents": [],
        "skipped_agents": [],
        "failed_agent": "SupervisorAgent",
        "error_type": "unexpected_supervisor_api_error",
        "error_message": (
            "Supervisor Agent execution failed before a structured "
            "SupervisorAgentOutput was returned."
        ),
        "blocking_reason": "The API could not complete query orchestration.",
        "execution_time_ms": 0.0,
        "metadata": {
            "agent": "FastAPIQueryEndpoint",
            "safe_fallback_response": True,
        },
    }