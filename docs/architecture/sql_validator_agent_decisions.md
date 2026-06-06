# SQL Validator / Guardrail Agent Architecture Decisions

## Status

Implemented, tested, and updated after trusted schema-resolution correction.

## Agent Name

SQL Validator / Guardrail Agent

## Implemented Files

```text
backend/app/agents/sql_validator_agent.py
backend/tests/agents/test_sql_validator_agent.py
backend/app/agents/__init__.py
backend/docs/architecture/sql_validator_agent_decisions.md
```

## Purpose

The SQL Validator / Guardrail Agent is responsible for validating generated SQL before it reaches the query execution layer.

Its main purpose is to act as a safety boundary between the Text-to-SQL Agent and the future Query Executor Agent.

The agent ensures that generated SQL is safe, valid, schema-aware, and suitable for execution against the local DuckDB analytics database.

## Design Decision: Agent Wraps the Existing Validator Service

The SQL Validator / Guardrail Agent does not duplicate SQL parsing or validation logic.

It wraps the existing service-layer function:

```python
validate_sql(sql: str, schema_context: dict) -> None
```

The service remains responsible for the actual SQL validation rules, while the agent is responsible for structured input/output handling, trusted schema-context resolution, dependency injection, error conversion, and audit metadata.

This keeps validation logic centralized and avoids maintaining duplicated SQL safety rules in multiple places.

## Design Decision: Trusted Schema Context Must Be Resolved Internally

The SQL Validator / Guardrail Agent does not accept caller-provided schema context, schema profile, table name, or allowed columns.

The input model intentionally does not include:

```text
schema_context
schema_profile
schema_context_override
table_name
allowed_columns
```

The caller provides only:

```text
dataset_id
question
sql
request_id optional
metadata optional
```

The agent internally resolves trusted schema context from `dataset_id`.

This is an important security and correctness decision because SQL validation depends on the real uploaded CSV table name and real schema columns. If callers could provide schema metadata manually, validation could accidentally or intentionally be performed against fake metadata instead of the actual registered dataset.

The trusted flow is:

```text
SQLValidatorAgentInput
    dataset_id + question + sql
        ↓
SQLValidatorAgent
        ↓
build_schema_context(dataset_id)
        ↓
validate_sql(sql, trusted_schema_context)
        ↓
structured validation output
```

## Design Decision: User/API Must Never Provide Schema Metadata Manually

The real product workflow should only accept the user question and dataset identifier from the caller.

The system must internally resolve trusted dataset metadata.

This matches the corrected project-wide rule:

```text
User/API provides dataset_id and question.
Agents resolve trusted schema context internally from dataset_id.
Raw CSV rows are never sent to the LLM.
LLM-dependent agents must not continue if schema context cannot be resolved.
SQL validation must use the real registered dataset metadata.
```

For the SQL Validator / Guardrail Agent specifically, this means validation is always based on the trusted schema context resolved from the dataset registry / schema context builder path.

## Design Decision: Extra Input Fields Are Forbidden

The agent input model uses strict input validation to reject unsupported caller-provided fields.

This prevents accidental use of unsafe fields such as:

```text
schema_context
schema_profile
table_name
allowed_columns
```

This keeps the agent boundary clean and prevents future workflow code from bypassing the trusted dataset metadata path.

## Design Decision: No SQL Execution Inside the Agent

The SQL Validator / Guardrail Agent does not execute SQL.

Execution belongs to the future Query Executor Agent.

The SQL Validator / Guardrail Agent only decides whether SQL is safe to execute.

This separation keeps the multi-agent workflow clean:

```text
Text-to-SQL Agent
    ↓
SQL Validator / Guardrail Agent
    ↓
Query Executor Agent
```

## Design Decision: No LangGraph Inside the Agent

LangGraph is not used inside the SQL Validator / Guardrail Agent.

The agent is implemented as a focused Python class/module.

LangGraph will later orchestrate agents at the workflow level through the Supervisor Agent.

Correct architecture:

```text
Agent = focused Python module/class
LangGraph = workflow orchestration layer
```

## Design Decision: Structured Input Model

The agent uses a structured input model:

```python
SQLValidatorAgentInput
```

The input includes:

```text
dataset_id
question
sql
request_id
metadata
```

The input does not include `schema_context` or `schema_profile`.

This keeps the SQL Validator Agent aligned with the trusted schema-resolution rule used by the corrected Text-to-SQL Agent.

## Design Decision: Structured Output Model

The agent returns:

```python
SQLValidatorAgentOutput
```

The output includes:

```text
success
dataset_id
question
sql
validation_status
is_valid
is_safe_to_execute
schema_context_source
error_type
error_message
blocking_reason
execution_time_ms
metadata
```

This makes the output suitable for API responses, tests, logging, and future LangGraph state transitions.

## Design Decision: Validation Status Enum

The agent uses a validation status enum:

```python
SQLValidationStatus
```

Supported statuses:

```text
valid
blocked
error
```

Meaning:

```text
valid   = SQL passed validation and is safe to execute
blocked = SQL was unsafe, unsupported, malformed, or invalid
error   = validation could not be completed because of missing trusted context or internal failure
```

This distinction is important because unsafe SQL and internal validation failures are different types of problems.

## Design Decision: Safe Execution Flag

The agent explicitly returns:

```python
is_safe_to_execute: bool
```

This field is intentionally included to make downstream orchestration simple.

The future Query Executor Agent should only execute SQL when:

```python
is_safe_to_execute is True
```

This makes the guardrail decision clear and machine-readable.

## Design Decision: Empty SQL Is Handled by the Guardrail Agent

The `sql` field in `SQLValidatorAgentInput` does not use:

```python
Field(..., min_length=1)
```

Instead, it uses:

```python
sql: str
```

This is intentional.

Empty SQL should not be blocked by Pydantic before the agent runs. Empty SQL is a guardrail condition, so the SQL Validator / Guardrail Agent returns structured output such as:

```text
success=False
validation_status=blocked
error_type=EMPTY_SQL
is_safe_to_execute=False
blocking_reason="Generated SQL is empty."
```

This is better for the future LangGraph workflow because the Supervisor Agent can receive a structured blocked result instead of handling a raw Pydantic exception.

Pydantic validation is still kept for identity fields such as:

```text
dataset_id
question
```

Only the empty SQL validation responsibility was moved into the guardrail agent.

## Design Decision: Empty SQL Is Blocked Before Schema Resolution

The agent blocks empty or whitespace-only SQL before resolving schema context.

This avoids unnecessary schema lookups when there is no SQL to validate.

The validator service is not called for empty SQL.

## Design Decision: Schema Context Source

The agent resolves schema context internally from `dataset_id`.

This is represented through:

```python
SQLValidatorSchemaContextSource
```

Supported value:

```text
built_from_dataset_id
```

The previous `provided` schema-context option was removed because caller-provided schema context is not allowed in the production workflow.

## Design Decision: Trusted Schema Context Is Validated Before SQL Validation

Before calling the SQL validator service, the agent checks that the internally resolved schema context contains the required structure.

Required schema-context fields include:

```text
table_name
schema_profile
schema_profile.columns
```

If trusted schema context is missing or invalid, the agent returns a structured error and does not call the validator service.

This prevents unclear downstream failures and makes debugging easier.

## Design Decision: Dependency Injection for Testability

The agent accepts injected dependencies:

```python
sql_validator
schema_context_builder
```

This makes the agent independently testable without relying on real database state, real dataset registry entries, or the real validator service during unit tests.

The injected `schema_context_builder` is used for testing and internal flexibility only. It does not mean callers can provide schema context directly through the agent input.

## Design Decision: Lazy Loading of the Validator Service

When no validator dependency is injected, the agent lazy-loads the real service:

```python
from app.services.sql_validator import validate_sql
```

This keeps imports controlled and avoids unnecessary dependency issues during isolated tests.

## Design Decision: Convert ValueError Into Structured Blocked Output

The existing SQL validator service raises `ValueError` for invalid or unsafe SQL.

The agent catches `ValueError` and converts it into structured blocked output:

```text
success=False
validation_status=blocked
error_type=SQL_VALIDATION_FAILED
is_safe_to_execute=False
blocking_reason=<validator error message>
```

This preserves the service-layer validation behavior while making the result usable by APIs and LangGraph orchestration.

## Design Decision: Unexpected Exceptions Are Treated Separately

Unexpected exceptions are not treated as normal SQL validation failures.

They return:

```text
validation_status=error
error_type=UNEXPECTED_VALIDATION_ERROR
is_safe_to_execute=False
```

This distinction helps separate unsafe user/model-generated SQL from internal system failures.

## Current Guardrail Coverage

The wrapped validator service currently blocks or validates:

```text
multiple SQL statements
forbidden SQL keywords
malformed SQL
non-SELECT queries
JOIN queries
subqueries
CTEs
invalid table references
invalid column references
```

The agent does not duplicate these rules. It relies on the validator service as the single source of truth.

## Metadata and Audit Support

The agent output includes metadata useful for debugging and audit trails:

```text
request_id
agent
service
table_name
row_count
column_count
schema_column_count
schema_context_available
schema_context_source
guardrail_passed
exception_type
```

This will be useful later for LangSmith, OpenTelemetry, query audit logging, and workflow debugging.

## Test Coverage

The SQL Validator / Guardrail Agent test file covers:

```text
safe SQL validation using trusted schema context from dataset_id
rejection of caller-provided schema_context
rejection of caller-provided table_name
rejection of caller-provided schema_profile
rejection of caller-provided allowed_columns
empty SQL blocking before schema resolution
whitespace SQL blocking before schema resolution
missing trusted schema context
invalid trusted table_name
invalid trusted schema_profile
invalid trusted columns metadata
validator-raised ValueError
validator service unavailable
unexpected validator exception
output serialization using to_dict()
```

The full agent test suite passed successfully after implementation and trusted schema-resolution cleanup.

## Important Non-Responsibilities

The SQL Validator / Guardrail Agent does not handle:

```text
natural language intent classification
SQL generation
SQL execution
data-quality analysis
chart selection
chart payload generation
answer formatting
LangGraph orchestration
```

These responsibilities belong to other agents or services in the CSV Insight Agent architecture.

## Final Decision

The SQL Validator / Guardrail Agent is implemented as a production-style guardrail wrapper around the existing SQL validator service.

It provides a structured, testable, trusted-schema-aware, audit-friendly safety boundary before SQL execution.

The final design ensures SQL validation is always based on internally resolved trusted dataset metadata, not caller-provided schema information.

This design is aligned with the overall enterprise-grade multi-agent architecture of the CSV Insight Agent project.
