# FastAPI Supervisor Integration Architecture Decisions

## Status

Implemented, tested, and ready for commit.

## Phase Name

FastAPI Supervisor Integration Phase

## Implemented Files

```text
backend/app/api/query.py
backend/app/agents/__init__.py
backend/tests/api/test_query.py
```

## Purpose

This document records the architectural and implementation decisions made while integrating the `SupervisorAgent` into the FastAPI `/query` endpoint.

The purpose of this phase was to replace the older manual endpoint-level orchestration with the real multi-agent workflow controlled by the Supervisor Agent.

Before this change, the `/query` endpoint directly called service-layer functions such as schema context building, SQL generation, SQL validation, query execution, result analysis, chart selection, chart payload building, and chart validation.

After this change, the `/query` endpoint delegates workflow orchestration to:

```python
SupervisorAgent.run(...)
```

The endpoint now returns:

```python
SupervisorAgentOutput.to_dict()
```

This keeps the API layer thin and makes the Supervisor Agent the single workflow orchestration boundary for CSV question answering.

---

## Main Architectural Decision

The `/query` endpoint no longer owns the analytics workflow.

The previous architecture looked like this:

```text
FastAPI /query endpoint
→ build schema context
→ generate SQL
→ validate SQL
→ execute query
→ analyze result
→ detect visualization intent
→ select chart
→ build chart payload
→ validate chart
→ return response
```

The new architecture is:

```text
FastAPI /query endpoint
→ SupervisorAgent.run(...)
→ SupervisorAgentOutput.to_dict()
```

This is the correct direction because the Supervisor Agent is responsible for LangGraph-based workflow orchestration, while the FastAPI endpoint should only act as the HTTP boundary.

---

## Decision: Keep FastAPI Endpoint Thin

The FastAPI endpoint should not duplicate the Supervisor workflow.

The endpoint is responsible only for:

```text
1. Accepting the public API request
2. Validating public request fields
3. Creating SupervisorAgentInput
4. Calling SupervisorAgent.run(...)
5. Returning SupervisorAgentOutput.to_dict()
6. Returning a safe fallback response if SupervisorAgent fails unexpectedly
```

The endpoint should not directly perform:

```text
- schema context building
- SQL generation
- SQL validation
- SQL execution
- result analysis
- data quality evaluation
- chart payload generation
- answer formatting
```

Those responsibilities belong inside the agent workflow.

---

## Decision: Supervisor Agent Owns LangGraph Orchestration

LangGraph remains inside the Supervisor Agent only.

Correct architecture:

```text
Agent = focused Python class/module
LangGraph = workflow orchestration layer
```

Individual agents remain normal Python classes/modules. They do not contain LangGraph.

The Supervisor Agent is the orchestration layer that decides which agents should run and when the workflow should stop.

---

## Decision: API Must Not Accept Trusted Schema Metadata

The API request model intentionally forbids extra fields.

The `/query` endpoint must not accept trusted schema metadata from the client, including:

```text
schema_context
schema_profile
schema_context_override
table_name
allowed_columns
```

This is important because trusted dataset metadata must be resolved internally from `dataset_id`.

The API should only accept safe public request fields:

```text
dataset_id
question
request_id
chart_generation_approved
approved_chart_type
metadata
```

This prevents the caller from injecting fake schema metadata, fake table names, or fake allowed columns into the workflow.

---

## Decision: Schema Context Resolution Stays Internal

The endpoint does not call `build_schema_context(...)` anymore.

Schema context resolution is now handled internally by downstream agents that need trusted dataset metadata.

This keeps the trust boundary clean:

```text
External caller
→ public request fields only
→ SupervisorAgentInput
→ internal agents resolve trusted metadata by dataset_id
```

Raw CSV rows must never be sent to the LLM. Only safe metadata and derived schema/profile information should be used where needed.

---

## Decision: Use FastAPI Dependency Injection for SupervisorAgent

The endpoint uses a dependency function for the Supervisor Agent.

This allows the production endpoint to use the real Supervisor Agent while tests can override it with a fake Supervisor.

Production path:

```text
/query endpoint
→ get_supervisor_agent()
→ SupervisorAgent.run(...)
```

Test path:

```text
/query endpoint
→ dependency override
→ FakeSupervisorAgent.run(...)
```

This makes API tests deterministic and prevents tests from calling real OpenAI or external services.

---

## Decision: Use Cached SupervisorAgent Instance

The dependency creates a cached Supervisor Agent instance instead of constructing a new Supervisor Agent on every request.

This avoids unnecessary repeated workflow construction.

The endpoint uses a singleton-style cached dependency through `lru_cache`.

This is suitable because the Supervisor Agent is an orchestration object and does not need to be recreated for every request.

---

## Decision: Add Safe API Fallback Response

If `SupervisorAgent.run(...)` raises an unexpected exception before returning a structured `SupervisorAgentOutput`, the API returns a safe structured error response.

The fallback response includes:

```text
success = false
workflow_status = failed
failed_agent = SupervisorAgent
error_type = unexpected_supervisor_api_error
final_response.response_type = error_message
chart_available = false
```

This prevents raw exceptions from leaking to the frontend and keeps the API response shape predictable.

---

## Decision: API Tests Mock the Supervisor

The new API tests do not call the real Supervisor workflow.

Instead, they use a fake Supervisor Agent through FastAPI dependency overrides.

This verifies the API integration boundary without depending on:

```text
- real OpenAI calls
- real LangGraph workflow execution
- real CSV datasets
- real DuckDB state
- external services
```

The purpose of these tests is not to retest every agent. The purpose is to verify that the FastAPI endpoint delegates correctly to the Supervisor Agent.

---

## API Test Coverage Added

The new API tests verify:

```text
1. /query calls SupervisorAgent.run(...)
2. successful analytics request returns Supervisor output
3. unsupported query response is preserved
4. clarification response is preserved
5. unexpected Supervisor failure returns a safe API fallback response
6. trusted schema metadata fields are rejected from the request body
7. trusted schema metadata is not forwarded to SupervisorAgentInput
```

The tested forbidden fields are:

```text
schema_context
schema_profile
schema_context_override
table_name
allowed_columns
```

---

## Important FastAPI Implementation Detail

The endpoint uses:

```python
@router.post("", response_model=None)
```

This is intentional.

The endpoint may return either a normal dictionary from `SupervisorAgentOutput.to_dict()` or a `JSONResponse` fallback when the Supervisor fails unexpectedly.

Without `response_model=None`, FastAPI may try to generate a Pydantic response model from an invalid mixed return annotation.

---

## Current Known Limitations

This phase only integrated Supervisor Agent v1 into the `/query` endpoint.

It did not add new workflow routes.

Supervisor v1 still intentionally does not fully support:

```text
schema_question
table_preview_query
dataset-level data_quality_query
```

Those routes should be handled in a future Supervisor v2 deterministic route expansion phase.

---

## Future Work

The next recommended development phase is:

```text
Supervisor v2 Deterministic Route Expansion
```

Recommended order:

```text
1. Add schema_question support
2. Add table_preview_query support
3. Add dataset-level data_quality_query support
```

These routes should be deterministic where possible and should not require LLM-based SQL generation unless absolutely necessary.

---

## Testing Result

The new API integration tests passed successfully.

```text
10 passed
```

The broader test suite also passed successfully after this integration.

---

## Final Decision Summary

The FastAPI `/query` endpoint is now a thin HTTP boundary.

The Supervisor Agent is now the single orchestration entry point for the main CSV analytics and visualization workflow.

This improves:

```text
- architectural separation
- workflow consistency
- testability
- API safety
- maintainability
- production readiness
```

The system is now correctly positioned for Supervisor v2 route expansion.
