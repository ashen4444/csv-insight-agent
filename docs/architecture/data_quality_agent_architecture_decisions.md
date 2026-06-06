# Data Quality Agent Architecture Decisions

## Status

Implemented, tested, and ready for commit.

## Agent Name

Data Quality Agent

## Implemented Files

```text
backend/app/agents/data_quality_agent.py
backend/app/services/data_quality_evaluator.py
backend/tests/agents/test_data_quality_agent.py
backend/app/agents/__init__.py
```

## Purpose

The Data Quality Agent is responsible for evaluating the quality and usability of executed query results before they are passed to downstream agents such as the Answer Formatter Agent, Chart Agent, Supervisor Agent, and future Data Cleaning Agent.

The agent does not modify data. It detects quality issues, reports structured warnings, and provides recommendations that downstream components can use to decide whether to continue, warn the user, avoid chart generation, or suggest a future cleaning action.

## Design Decision: Agent Wraps a Deterministic Service Layer

The Data Quality Agent was implemented as a production-style wrapper around a deterministic service-layer module:

```text
backend/app/services/data_quality_evaluator.py
```

This keeps the agent wrapper focused on orchestration-facing responsibilities:

```text
input validation
upstream execution-state handling
trusted schema metadata resolution
service invocation
structured output formatting
error normalization
metadata generation
```

The actual quality-checking logic lives in the service layer, which keeps the implementation modular, testable, and reusable.

## Design Decision: No LLM Usage

The Data Quality Agent does not call an LLM.

Data-quality checks are deterministic and based on:

```text
query execution output
result row count
result shape
result null values
trusted schema profile metadata
column null percentages
unique counts
duplicate metadata if available
result analysis heuristics
```

This avoids unnecessary cost, latency, and nondeterminism. It also keeps the data-quality layer explainable and predictable.

## Design Decision: Trusted Schema Resolution Only

The Data Quality Agent does not accept caller-provided schema context, schema profile, table name, or allowed columns.

The agent resolves trusted dataset metadata internally using:

```python
build_schema_context(dataset_id)
```

This follows the same trusted metadata boundary already used by the Text-to-SQL Agent and SQL Validator / Guardrail Agent.

The agent input intentionally forbids fields such as:

```text
schema_context
schema_profile
schema_context_override
table_name
allowed_columns
```

This prevents users or API callers from injecting untrusted metadata into the agent workflow.

## Design Decision: Separate Result-Level Quality From Dataset-Level Quality

The Data Quality Agent distinguishes between:

```text
executed query result quality
trusted dataset/profile quality
```

For example:

```text
A query result may be empty even when the dataset itself is valid.
A query result may have no null values even when the source dataset has null-heavy columns.
A result may be usable for a textual answer but unsuitable for chart generation.
```

This separation is important because downstream agents need different signals depending on the task.

The Answer Formatter Agent may still be able to explain a result with warnings, while the Chart Agent may decide not to generate a visualization from the same result.

## Design Decision: Data Quality Agent Is Not a Data Cleaning Agent

The Data Quality Agent only detects issues and recommends possible actions.

It does not:

```text
drop rows
fill missing values
remove duplicates
create cleaned dataset versions
mutate query results
modify the uploaded dataset
```

Data cleaning is reserved for a future Data Cleaning Agent.

The future Data Cleaning Agent should require explicit user approval, keep the original dataset immutable, create a new cleaned dataset version, and log every transformation.

## Design Decision: Use `quality_not_evaluated` Instead of `quality_skipped`

The Data Quality Agent uses the following quality status values:

```text
quality_passed
quality_warning
quality_failed
quality_not_evaluated
```

`quality_not_evaluated` is used when upstream query execution failed or was blocked, meaning data-quality checks were not performed.

This name is clearer and more professional than `quality_skipped` because it explains that evaluation did not happen due to an upstream dependency failure.

## Quality Status Meanings

```text
quality_passed
```

The result is usable and no major quality warnings were detected.

```text
quality_warning
```

The result is usable, but one or more warnings were detected.

```text
quality_failed
```

The result is not usable, the result payload is invalid, trusted metadata is unavailable, or a blocking quality issue was detected.

```text
quality_not_evaluated
```

Upstream execution failed or was blocked, so quality checks were not performed.

## Structured Warning Model

Warnings are structured instead of being plain strings.

Each warning includes:

```text
warning_type
severity
message
column
recommendation
metadata
```

Supported severity levels:

```text
info
warning
critical
```

This makes the output useful for downstream agents and future LangGraph orchestration.

## Structured Recommendation Model

Recommendations are also structured.

Each recommendation includes:

```text
recommendation_type
priority
message
column
metadata
```

Supported priority levels:

```text
low
medium
high
```

This allows downstream agents to decide whether the recommendation should be shown to the user, used internally, or passed to a future Data Cleaning Agent.

## Quality Checks Implemented

The first implementation supports deterministic checks for:

```text
empty query results
invalid result payloads
inconsistent result shapes
large result sets
chart-readiness warnings
result-level null values
dataset-level null-heavy columns
high-cardinality categorical columns
duplicate-result rows
duplicate-row metadata if available in schema profile
```

## Upstream Execution Handling

The Data Quality Agent expects to receive output from the Query Executor Agent.

If upstream execution failed, was blocked, or was not executed, the Data Quality Agent returns:

```text
success = false
quality_status = quality_not_evaluated
error_type = execution_not_successful
is_result_usable = false
```

In this case, trusted schema context is not resolved and quality checks are not performed.

This prevents the system from pretending that data quality was evaluated when the query never successfully executed.

## Integration With Query Executor Agent

The Data Quality Agent is aligned with the Query Executor Agent output fields:

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

This keeps the wrapper ready for future Supervisor Agent and LangGraph orchestration.

## Output Contract

The Data Quality Agent returns structured output including:

```text
success
dataset_id
question
sql
quality_status
is_result_usable
is_result_empty
is_result_too_large
has_null_warnings
has_duplicate_warnings
has_visualization_warnings
row_count
execution_time_ms
warnings
recommendations
error_type
error_message
blocking_reason
metadata
```

The output is designed to be directly consumed by:

```text
Answer Formatter Agent
Chart Agent
Supervisor Agent with LangGraph
future Data Cleaning Agent
```

## Error Types

The agent defines structured error types for expected failure modes:

```text
schema_context_not_found
invalid_schema_context
execution_not_successful
invalid_result_payload
data_quality_service_unavailable
invalid_quality_response
unexpected_quality_error
```

These error types make failures easier to test, debug, log, and route in the future workflow.

## Service-Layer Design

A new deterministic service was added:

```text
backend/app/services/data_quality_evaluator.py
```

The service performs quality evaluation and returns a plain dictionary containing status, warnings, recommendations, flags, and metadata.

The agent then validates and converts this response into strongly typed Pydantic output models.

This separation keeps the service reusable and keeps the agent wrapper focused on workflow-facing behavior.

## Testing Decisions

A dedicated test file was added:

```text
backend/tests/agents/test_data_quality_agent.py
```

The tests cover:

```text
successful quality evaluation
compatibility with Query Executor Agent output
rejection of caller-provided schema context
rejection of caller-provided schema profile
rejection of caller-provided table name
rejection of caller-provided allowed columns
quality_not_evaluated for failed upstream execution
missing schema context handling
invalid schema context handling
invalid result payload handling
empty result handling
null-heavy dataset warnings
result-level null warnings
large visualization warning
high-cardinality warning
duplicate metadata warning
to_dict serialization
```

## Privacy Boundary

The Data Quality Agent follows the project privacy rule:

```text
Raw CSV rows must never be sent to the LLM.
```

Since this agent does not use an LLM, no raw rows are externally transmitted.

The agent only uses local execution results and trusted local schema metadata.

## LangGraph Decision

LangGraph is not used inside the Data Quality Agent.

The correct architecture remains:

```text
Agent = focused Python module/class
LangGraph = workflow orchestration layer
```

The Data Quality Agent is independently testable and will later be orchestrated by the Supervisor Agent.

## Future Extension Points

Possible future improvements include:

```text
adding duplicate-row counts to the schema profiler
adding data freshness checks if upload timestamps become relevant
adding stronger type-anomaly detection
adding configurable thresholds
adding integration with the future Data Cleaning Agent
adding OpenTelemetry or LangSmith tracing metadata
```

These are intentionally left as future improvements to avoid over-engineering the first production wrapper.

## Final Decision

The Data Quality Agent is implemented as a deterministic, production-style wrapper that evaluates executed query results using trusted dataset metadata.

It does not clean or mutate data.

It returns structured quality statuses, warnings, recommendations, and metadata suitable for downstream Answer Formatter, Chart Agent, Supervisor Agent, and future Data Cleaning Agent integration.
