# Text-to-SQL Agent Architecture Decisions

## Purpose

This document records the architectural and implementation decisions made during the Text-to-SQL Agent wrapper phase of the CSV Insight Agent project.

The Text-to-SQL Agent is part of the final production-oriented multi-agent workflow. It is designed as an independently testable agent-level wrapper around the existing SQL generation service, while remaining ready for future LangGraph orchestration through the Supervisor Agent.

This document also records the later schema-context correction made after formalizing the Data Profiler Agent wrapper.

---

## Agent Role

The Text-to-SQL Agent is responsible for converting a user’s natural language analytical question into a SQL query using trusted schema context for the uploaded CSV dataset.

The agent does not directly perform SQL validation, SQL execution, result analysis, chart generation, data-quality analysis, or final answer formatting. Those responsibilities belong to separate agents or service-layer components.

The Text-to-SQL Agent focuses on:

* accepting restricted structured input,
* resolving trusted schema context internally from `dataset_id`,
* validating schema context before SQL generation,
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
schema_context_builder.py / Data Profiler-compatible schema context path
    ↓
sql_generator.py
    ↓
llm_client.py
```

The Text-to-SQL Agent is responsible for coordination, trusted schema resolution, validation, and structured output.

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

The Text-to-SQL Agent accepts a restricted structured Pydantic input model:

```python
TextToSQLAgentInput
```

The final accepted input fields are:

```text
dataset_id
question
request_id optional
metadata optional
```

The agent intentionally does not accept:

```text
schema_context
schema_profile
table_name
columns
allowed_columns
raw rows
```

This correction was made after formalizing the Data Profiler Agent wrapper and clarifying the real product workflow.

In the real system, the user/API should only provide the uploaded dataset identifier and the natural language question. The system must internally resolve trusted schema context from `dataset_id`.

Allowing caller-provided schema context would be misleading and unsafe because it could bypass the actual uploaded CSV metadata stored by the backend.

---

## Trusted Schema Context Resolution Decision

The Text-to-SQL Agent always resolves schema context internally from `dataset_id`.

The final flow is:

```text
TextToSQLAgentInput(dataset_id, question)
    -> resolve trusted schema context from dataset_id
    -> validate schema context
    -> call SQL generation service
    -> return structured TextToSQLAgentOutput
```

The agent uses the existing trusted schema context path / Data Profiler-compatible flow instead of accepting schema metadata from the caller.

This ensures that SQL generation is grounded only in backend-controlled dataset metadata.

The LLM must not be called if trusted schema context cannot be resolved.

If schema context is missing or invalid, the agent returns a structured failure response instead of attempting SQL generation.

---

## Schema Context Security Decision

The Text-to-SQL Agent must never receive schema context, schema profile, table name, or column lists from the user/API layer.

This protects the system from accidental or malicious metadata injection.

The trusted schema context must come from the backend dataset registry / profiler flow associated with the provided `dataset_id`.

This rule supports the project-wide privacy and safety policy:

```text
User must never provide schema_context or schema_profile manually.
Agents must resolve trusted schema context internally from dataset_id.
Raw CSV rows must never be sent to the LLM.
LLM must not be called if trusted schema context cannot be resolved.
```

---

## Raw CSV Row Protection Decision

The Text-to-SQL Agent only sends schema metadata and safe summary information to the SQL generation service.

Raw CSV rows must never be sent to the LLM.

The agent validates schema context and rejects suspicious raw-row payload keys such as:

```text
rows
records
raw_rows
csv_rows
dataframe
```

This reinforces the privacy rule that the LLM receives only trusted schema/profile metadata, not raw uploaded data.

---

## Schema Context Validation Decision

The agent validates that the resolved schema context contains:

* a valid `table_name`,
* a valid `schema_profile` dictionary,
* a valid `columns` list inside `schema_profile`,
* no raw-row payload keys.

This validation was added because the SQL generator depends on trusted schema metadata to produce safe, schema-aware SQL.

Invalid schema context results in a structured failure output instead of an unhandled runtime error.

---

## Schema Context Source Decision

The previous design allowed multiple schema context sources, including caller-provided schema context.

That design has been corrected.

The final schema context source is:

```text
resolved_from_dataset_id
```

This means the agent always resolves schema context internally from the backend using the provided `dataset_id`.

The agent no longer supports a `provided` schema context source.

---

## Model Availability Decision

Text-to-SQL generation is LLM-dependent.

The Text-to-SQL Agent itself no longer accepts a caller-provided `model_available` field as input.

Model/API availability is expected to be handled by the upstream routing or supervisor layer before the Text-to-SQL Agent is called.

This keeps `TextToSQLAgentInput` focused on the real product workflow:

```text
dataset_id
question
request_id optional
metadata optional
```

If the SQL generation service cannot be loaded or fails during execution, the Text-to-SQL Agent returns a structured failure response.

This preserves predictable downstream behavior without allowing the user/API to control model availability state manually.

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

Dependency injection is for internal testing and composition only. It does not mean user/API callers can provide schema context or schema profile manually.

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

The updated tests cover:

* rejecting caller-provided `schema_context`,
* rejecting caller-provided `schema_profile`,
* successful SQL generation after resolving schema context from `dataset_id`,
* not calling the SQL generator when schema context is missing,
* invalid table name,
* invalid schema profile,
* missing schema columns,
* raw row payload detection in schema context,
* raw row payload detection in schema profile,
* empty SQL generator response,
* SQL generator failure,
* result serialization.

The Text-to-SQL Agent test suite passed successfully after the cleanup.

---

## Final Design Summary

The final Text-to-SQL Agent is a production-style wrapper around the existing SQL generation service.

It provides a clean agent boundary, restricted structured input, trusted internal schema context resolution, dependency injection, lazy loading, schema validation, raw-row protection, metadata, structured error handling, and strong unit test coverage.

The implementation is ready for future integration into the LangGraph-based Supervisor Agent workflow.
