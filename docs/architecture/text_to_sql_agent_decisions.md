# Text-to-SQL Agent Architecture Decisions

## Purpose

This document records the architectural and implementation decisions made during the Text-to-SQL Agent wrapper phase of the CSV Insight Agent project.

The Text-to-SQL Agent is part of the final production-oriented multi-agent workflow. It is designed as an independently testable agent-level wrapper around the existing SQL generation service, while remaining ready for future LangGraph orchestration through the Supervisor Agent.

---

## Agent Role

The Text-to-SQL Agent is responsible for converting a user’s natural language analytical question into a SQL query using the uploaded CSV dataset schema context.

The agent does not directly perform SQL validation, SQL execution, result analysis, chart generation, or final answer formatting. Those responsibilities belong to separate agents or service-layer components.

The Text-to-SQL Agent focuses on:

* accepting structured input,
* resolving schema context,
* respecting model/API availability decisions,
* calling the existing SQL generation service,
* returning structured success/error output,
* exposing metadata useful for audit, debugging, and future orchestration.

---

## Final File Location

The Text-to-SQL Agent wrapper was implemented in:

```text
backend/app/agents/text_to_sql_agent.py
```

The test file was implemented in:

```text
backend/tests/agents/test_text_to_sql_agent.py
```

The agent was also exported through:

```text
backend/app/agents/__init__.py
```

---

## Service Layer Separation Decision

The existing SQL generation logic remains in the service layer:

```text
backend/app/services/sql_generator.py
```

The Text-to-SQL Agent does not duplicate prompt construction or LLM call logic.

The existing service function is:

```python
generate_sql_from_question(
    table_name: str,
    schema_profile: dict,
    question: str,
) -> str
```

The agent wraps this function instead of replacing it.

This separation was chosen because SQL generation is reusable technical logic. It may be reused by FastAPI endpoints, tests, future LangGraph nodes, evaluation scripts, or debugging utilities.

The agent layer provides workflow-facing structure and orchestration readiness, while the service layer performs the actual SQL generation work.

---

## Agent vs Service Responsibility Boundary

The responsibility boundary is:

```text
TextToSQLAgent
    ↓
schema_context_builder.py
    ↓
sql_generator.py
    ↓
llm_client.py
```

The Text-to-SQL Agent is responsible for coordination and structured output.

The `sql_generator.py` service is responsible for SQL prompt creation and LLM-based SQL generation.

The `llm_client.py` service is responsible for calling the configured OpenAI model.

---

## No LangGraph Inside the Agent

LangGraph was intentionally not introduced inside the Text-to-SQL Agent.

The project architecture rule is:

```text
Agent = focused Python module/class
LangGraph = workflow orchestration layer
```

Therefore, the Text-to-SQL Agent is implemented as a focused Python class that can later be called from a LangGraph node by the Supervisor Agent.

This keeps the agent independently testable and avoids mixing local agent logic with global workflow orchestration.

---

## Structured Input Decision

The agent accepts a structured Pydantic input model:

```python
TextToSQLAgentInput
```

The input includes:

* `dataset_id`
* `question`
* optional `schema_context`
* `model_available`
* optional `request_id`
* optional `metadata`

This makes the agent suitable for future workflow orchestration because the Supervisor Agent can pass already-resolved state into the Text-to-SQL Agent.

---

## Schema Context Resolution Decision

The Text-to-SQL Agent supports two schema context modes:

1. Use a provided schema context.
2. Build schema context internally from `dataset_id`.

If `schema_context` is provided, the agent uses it directly.

If it is not provided, the agent calls:

```python
build_schema_context(dataset_id)
```

from:

```text
backend/app/services/schema_context_builder.py
```

This allows the agent to work both independently and inside a future orchestrated LangGraph workflow.

---

## Schema Context Validation Decision

The agent validates that the schema context contains:

* a valid `table_name`
* a valid `schema_profile` dictionary
* a valid `columns` list inside `schema_profile`

This validation was added because the SQL generator depends on schema metadata to produce safe, schema-aware SQL.

Invalid schema context results in a structured failure output instead of an unhandled runtime error.

---

## Model Availability Decision

Text-to-SQL generation is LLM-dependent.

If the model/API is unavailable, the agent should not attempt SQL generation.

The agent accepts:

```python
model_available: bool
```

When `model_available` is `False`, the agent returns a structured failure with:

```text
error_type = model_unavailable
```

This follows the project-wide decision that LLM-dependent analytics workflows should not pretend to continue when the model/API is unavailable.

The model availability decision is expected to come from the routing or supervisor layer.

---

## Lazy SQL Generator Loading Decision

The SQL generator is lazy-loaded only when needed.

This was chosen because:

```text
backend/app/services/llm_client.py
```

creates the OpenAI client at import time.

Lazy loading prevents unit tests from failing due to missing OpenAI configuration when fake SQL generators are injected.

This improves testability and keeps the agent safer for isolated test execution.

---

## Dependency Injection Decision

The Text-to-SQL Agent supports dependency injection for:

* `sql_generator`
* `schema_context_builder`

This allows tests to use fake dependencies instead of calling the real OpenAI-backed SQL generator or the real dataset registry.

This decision keeps the agent independently testable and avoids unnecessary external dependency usage during unit tests.

---

## Structured Output Decision

The agent returns a structured Pydantic output model:

```python
TextToSQLAgentOutput
```

The output includes:

* `success`
* `dataset_id`
* `question`
* generated `sql`
* `model_required`
* `model_available`
* `schema_context_source`
* `error_type`
* `error_message`
* `execution_time_ms`
* `metadata`

The output also includes:

```python
to_dict()
```

for serialization consistency with other agents.

This makes the Text-to-SQL Agent suitable for future LangGraph state updates, API responses, audit logging, and debugging.

---

## Error Handling Decision

The Text-to-SQL Agent returns structured error states instead of raising unhandled exceptions to the caller.

Supported error types include:

```text
model_unavailable
schema_context_not_found
invalid_schema_context
sql_generator_unavailable
sql_generation_failed
empty_sql_generated
```

This makes downstream workflow behavior more predictable and easier to handle inside the future Supervisor Agent.

---

## Non-Responsibilities

The Text-to-SQL Agent intentionally does not perform:

* SQL validation,
* SQL safety checking,
* query execution,
* result analysis,
* chart selection,
* chart payload generation,
* final answer formatting,
* data-quality analysis.

These tasks belong to other agents or existing services.

This keeps the Text-to-SQL Agent focused and avoids creating a large, tightly coupled component.

---

## Relationship to Existing Services

The Text-to-SQL Agent depends on existing services instead of duplicating them.

Relevant services include:

```text
backend/app/services/schema_context_builder.py
backend/app/services/sql_generator.py
backend/app/services/llm_client.py
```

This preserves the service-layer architecture and keeps business/technical logic reusable outside the agent layer.

---

## Testing Decision

A dedicated unit test file was created:

```text
backend/tests/agents/test_text_to_sql_agent.py
```

The tests cover:

* successful SQL generation with provided schema context,
* schema context building when not provided,
* model unavailable blocking,
* missing schema context,
* invalid table name,
* invalid schema profile,
* missing schema columns,
* empty SQL generator response,
* SQL generator failure,
* result serialization.

The Text-to-SQL Agent test suite passed successfully:

```text
10 passed
```

---

## Final Design Summary

The final Text-to-SQL Agent is a production-style wrapper around the existing SQL generation service.

It provides a clean agent boundary, structured input/output, dependency injection, lazy loading, model availability awareness, schema validation, metadata, and strong unit test coverage.

The implementation is ready for future integration into the LangGraph-based Supervisor Agent workflow.
