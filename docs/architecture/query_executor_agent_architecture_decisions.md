# Query Executor Agent Architecture Decisions

## Status

Implemented, tested, and ready for commit.

## Agent Name

Query Executor Agent

## Implemented Files

```text
backend/app/agents/query_executor_agent.py
backend/tests/agents/test_query_executor_agent.py
backend/app/agents/__init__.py
```

## Purpose

This document records the architectural and implementation decisions made during the Query Executor Agent wrapper phase of the CSV Insight Agent project.

The Query Executor Agent is part of the final production-oriented multi-agent workflow. It is responsible for safely executing SQL only after the SQL Validator / Guardrail Agent has confirmed that the SQL is safe to run.

This agent acts as the controlled execution boundary between validated SQL and the local DuckDB analytics database.

---

## Agent Role

The Query Executor Agent is responsible for executing validated SQL and returning structured execution results.

The agent does not generate SQL, validate SQL safety rules, rewrite SQL, analyze data quality, generate charts, or format final natural-language answers. Those responsibilities belong to separate agents or service-layer components.

The Query Executor Agent focuses on:

* accepting structured execution input,
* enforcing the validation gate before execution,
* refusing unsafe or unvalidated SQL,
* calling the existing query execution service,
* returning structured success/error output,
* returning query results, row count, and execution time,
* exposing metadata useful for audit, debugging, and later LangGraph orchestration.

---

## Final File Location

The Query Executor Agent wrapper was implemented in:

```text
backend/app/agents/query_executor_agent.py
```

The corresponding unit tests were implemented in:

```text
backend/tests/agents/test_query_executor_agent.py
```

The agent exports were added to:

```text
backend/app/agents/__init__.py
```

---

## Design Decision: Agent Wraps the Existing Query Executor Service

The Query Executor Agent does not duplicate query execution logic.

It wraps the existing service-layer function:

```python
execute_query(sql: str) -> dict
```

The existing service already handles:

* applying a safe LIMIT,
* executing SQL against DuckDB,
* enforcing query timeout interruption,
* converting DuckDB execution errors into `ValueError`,
* serializing Pandas, NumPy, datetime, date, and Decimal values,
* returning SQL, row count, execution time, and results.

The agent layer is responsible only for orchestration-safe execution control and structured output.

This keeps the system layered and maintainable:

```text
Query Executor Agent = execution gate and structured wrapper
query_executor.py service = actual DuckDB execution logic
```

---

## Design Decision: SQL Must Be Marked Safe Before Execution

The Query Executor Agent does not trust SQL blindly.

Even if SQL text is provided, the agent executes only when:

```text
is_safe_to_execute=True
```

If `is_safe_to_execute=False`, execution is blocked before the query execution service is called.

This ensures that SQL execution cannot bypass the SQL Validator / Guardrail Agent.

Blocked unsafe execution returns structured output with:

```text
success=False
executed=False
execution_status=execution_blocked
error_type=unsafe_sql
```

---

## Design Decision: Optional Validation Status Gate

The Query Executor Agent accepts:

```text
validation_status optional
```

When `validation_status` is provided, the agent blocks execution unless the value is:

```text
valid
```

This adds a second guardrail while still allowing future orchestration flexibility.

For example:

```text
is_safe_to_execute=True
validation_status=error
```

will still be blocked because the validation status is not valid.

This prevents inconsistent upstream state from accidentally triggering execution.

---

## Final Query Executor Agent Input

The final input model is:

```text
dataset_id
question
sql
is_safe_to_execute
validation_status optional
request_id optional
metadata optional
```

The input model uses:

```python
model_config = ConfigDict(extra="forbid")
```

This prevents callers from passing untrusted execution metadata such as:

```text
schema_context
schema_profile
table_name
allowed_columns
```

The Query Executor Agent does not need caller-provided schema context because it is not responsible for schema validation. SQL validation has already been handled by the SQL Validator / Guardrail Agent.

---

## Final Query Executor Agent Output

The final output model includes:

```text
success
dataset_id
question
sql
executed
execution_status
results
row_count
execution_time_ms
error_type
error_message
blocking_reason
metadata
```

The output also exposes:

```python
to_dict()
```

for JSON-safe serialization during API integration, testing, audit logging, and later LangGraph state transitions.

---

## Execution Status Enum

The agent defines a structured execution status enum:

```text
execution_succeeded
execution_blocked
execution_failed
```

These statuses separate three different outcomes:

```text
execution_succeeded = SQL was safely executed
execution_blocked = SQL was not executed because a guardrail blocked it
execution_failed = SQL reached execution but failed due to service/runtime error
```

This distinction is important for future workflow orchestration and user-facing error handling.

---

## Error Type Enum

The agent defines structured error types:

```text
empty_sql
unsafe_sql
validation_not_passed
query_executor_unavailable
query_execution_failed
invalid_executor_response
unexpected_execution_error
```

These error types make failures easier to test, audit, and route in the future Supervisor Agent.

For example:

```text
unsafe_sql
```

means execution was correctly blocked before reaching DuckDB.

```text
query_execution_failed
```

means SQL passed the execution gate but the query execution service raised a controlled `ValueError`.

```text
unexpected_execution_error
```

means an unexpected runtime exception occurred and should be treated as an internal system issue.

---

## Design Decision: Empty SQL Is Blocked Before Service Call

The Query Executor Agent blocks empty or whitespace-only SQL before calling the query execution service.

This avoids unnecessary service execution and returns structured output:

```text
success=False
executed=False
execution_status=execution_blocked
error_type=empty_sql
blocking_reason="SQL is empty."
```

This mirrors the structured error-handling style used in the SQL Validator / Guardrail Agent.

---

## Design Decision: Query Executor Service Is Dependency-Injected

The agent supports dependency injection through:

```python
QueryExecutorAgent(query_executor=...)
```

This allows the query execution service to be replaced in unit tests without touching DuckDB.

If no custom executor is provided, the agent lazily imports:

```python
from app.services.query_executor import execute_query
```

This improves testability and avoids unnecessary service loading during isolated tests.

---

## Design Decision: Query Execution Service Response Is Validated

The agent validates the shape of the query execution service response before returning success.

The expected service response must include:

```text
sql
row_count
execution_time_ms
results
```

The response must satisfy:

```text
sql must be a non-empty string
row_count must be an integer
execution_time_ms must be int or float
results must be a list
each result row must be a dictionary
```

If the response shape is invalid, the agent returns:

```text
success=False
executed=False
execution_status=execution_failed
error_type=invalid_executor_response
```

This protects the workflow from malformed downstream service responses.

---

## Design Decision: Agent Execution Time and Service Execution Time Are Separated

The existing query execution service returns:

```text
execution_time_ms
```

This represents the service-level query execution time.

The Query Executor Agent also records:

```text
agent_execution_time_ms
```

inside metadata.

This distinction is useful because the agent may perform additional orchestration checks before and after calling the service.

---

## Design Decision: Safe LIMIT Changes Are Preserved

The query execution service may return SQL that differs from the original SQL because it applies a safe LIMIT.

The Query Executor Agent preserves both:

```text
original_sql
service_returned_sql
```

It also records:

```text
safe_limit_may_have_been_applied
```

This supports auditability and helps explain why executed SQL may differ from generated SQL.

---

## Non-Responsibilities

The Query Executor Agent does not perform:

* natural language intent routing,
* schema profiling,
* SQL generation,
* SQL validation,
* SQL safety rule inspection,
* SQL rewriting,
* data-quality analysis,
* chart selection,
* chart payload generation,
* final answer formatting,
* LangGraph orchestration.

These responsibilities remain separated across the multi-agent architecture.

---

## Relationship to Previous Agents

The Query Executor Agent depends on the output of the SQL Validator / Guardrail Agent.

Expected upstream flow:

```text
Text-to-SQL Agent
→ SQL Validator / Guardrail Agent
→ Query Executor Agent
```

The SQL Validator / Guardrail Agent provides:

```text
sql
is_safe_to_execute
validation_status
```

The Query Executor Agent uses those fields to decide whether execution is allowed.

---

## Future LangGraph Orchestration Role

The Query Executor Agent is designed to be used later inside the Supervisor Agent’s LangGraph workflow.

Expected future orchestration pattern:

```text
Intent Router Agent
→ Data Profiler Agent if needed
→ Text-to-SQL Agent
→ SQL Validator / Guardrail Agent
→ Query Executor Agent
→ Data Quality Agent
→ Chart Agent or Answer Formatter Agent
```

The Query Executor Agent itself does not use LangGraph internally.

This follows the project-level architecture rule:

```text
Agent = focused Python module/class
LangGraph = workflow orchestration layer
```

---

## Testing Decisions

The test suite covers:

* successful execution of safe validated SQL,
* rejection of caller-provided schema context,
* rejection of caller-provided table name,
* rejection of caller-provided schema profile,
* rejection of caller-provided allowed columns,
* blocking empty SQL,
* blocking whitespace SQL,
* blocking SQL when `is_safe_to_execute=False`,
* blocking SQL when validation status is not valid,
* execution when validation status is omitted but SQL is marked safe,
* query executor service unavailable,
* query executor service `ValueError`,
* unexpected query executor exception,
* invalid query executor response shape,
* output serialization through `to_dict()`.

The expected test command from the project root is:

```powershell
python -m pytest backend/tests/agents -q
```

---

## Runtime File Note

Generated runtime files should not be committed.

In particular, avoid committing:

```text
backend/data/query_audit_logs.jsonl
```

If needed, runtime log files should be added to `.gitignore`.

---

## Summary

The Query Executor Agent provides a production-grade execution boundary for the CSV Insight Agent workflow.

It ensures that SQL is executed only after validation has approved it, wraps the existing DuckDB execution service without duplicating service logic, returns structured execution output, and remains independently testable and ready for later LangGraph orchestration.
