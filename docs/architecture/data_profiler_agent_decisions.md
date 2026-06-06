# Data Profiler Agent Architecture Decisions

## Status

Implemented, tested, and ready for commit.

## Agent Name

Data Profiler Agent

## Implemented Files

```text
backend/app/agents/data_profiler_agent.py
backend/tests/agents/test_data_profiler_agent.py
```

## Purpose

The Data Profiler Agent is responsible for resolving safe dataset metadata and schema context for a registered CSV dataset.

This agent formalizes the profiling layer as part of the production-style multi-agent workflow. Earlier in the project, profiling already existed as service-layer functionality, but there was no dedicated agent wrapper for it. The Data Profiler Agent fixes that architecture sequencing issue by exposing profiling and schema-context resolution through a structured, testable agent interface.

The agent does not duplicate the existing profiling or registry logic. Instead, it coordinates the existing services and returns a consistent output structure that future agents and the LangGraph Supervisor can use.

## Why This Agent Was Added

The CSV Insight Agent platform is designed as an enterprise-grade multi-agent analytics system, not a lightweight demo.

The finalized workflow includes a dedicated Data Profiler Agent before the Text-to-SQL Agent. This is important because the Text-to-SQL Agent should not receive schema information directly from the user or caller. The system itself must resolve dataset metadata, schema profile, table name, allowed columns, and schema context from the uploaded CSV and internal registry.

Adding this wrapper makes the architecture more consistent with the intended agent workflow:

```text
CSV Upload
→ Schema Profiling
→ Dataset Registry
→ Data Profiler Agent
→ Text-to-SQL Agent
→ SQL Validator / Guardrail Agent
→ Query Executor Agent
→ Data Quality / Chart / Answer Formatter Agents
→ Supervisor Agent with LangGraph
```

## Service-Layer Dependencies

The Data Profiler Agent wraps and coordinates these existing services:

```text
backend/app/services/dataset_registry.py
backend/app/services/schema_context_builder.py
```

The dataset registry is responsible for storing and retrieving dataset metadata, including:

```text
dataset_id
original_filename
saved_filename
table_name
row_count
column_count
schema_profile
uploaded_at
```

The schema context builder is responsible for constructing the context package required by downstream agents.

The Data Profiler Agent does not replace these services. It provides an agent-level boundary around them.

## schema_profile vs schema_context

A key design clarification made during this phase is that `schema_profile` and `schema_context` are different concepts.

### schema_profile

`schema_profile` is created from the uploaded CSV during the upload/profiling stage.

It describes column-level metadata such as:

```text
column names
inferred column types
null counts
unique counts
safe summary statistics
dataset row count
dataset column count
```

The schema profile is safe metadata. It should not contain raw CSV rows.

### schema_context

`schema_context` is built from stored dataset metadata.

It contains the full context package needed by downstream agents, especially the Text-to-SQL Agent.

The schema context includes:

```text
dataset_id
table_name
row_count
column_count
schema_profile
```

The schema context is system-generated and must not be supplied manually by the user.

## Product Workflow Rule

The real product workflow should only accept:

```text
CSV upload
user question
```

The user should not provide:

```text
schema_context
schema_profile
table_name
allowed_columns
raw SQL execution context
```

Those values must be generated internally by the system.

This decision protects the platform from schema injection, table-name spoofing, invalid metadata, and unsafe caller-controlled context.

## Privacy and Security Rule

The Data Profiler Agent is deterministic and service-based.

It must never call the LLM.

It must never send raw CSV rows to the LLM.

It should only return safe dataset metadata and schema context created from the uploaded CSV and stored registry information.

This supports the project’s core privacy rule:

```text
Raw CSV rows stay local.
Only safe metadata and controlled query results move through the agent workflow.
```

## Agent Input

The Data Profiler Agent accepts:

```text
dataset_id
request_id optional
metadata optional
```

The input intentionally does not include `schema_context` or `schema_profile`.

## Agent Output

The Data Profiler Agent returns structured output with fields such as:

```text
success
dataset_id
table_name
row_count
column_count
schema_profile
schema_context
profiling_status
error_type
message
request_id
metadata
```

This output format is designed to be easy for future LangGraph orchestration to consume.

## Expected Runtime Behavior

The Data Profiler Agent follows this process:

```text
1. Accept dataset_id.
2. Look up the dataset in the dataset registry.
3. Validate that the dataset exists.
4. Validate that schema_profile exists.
5. Build schema_context using schema_context_builder.py.
6. Validate that the schema_context contains required fields.
7. Return structured success or failure output.
8. Never call the LLM.
9. Never expose raw CSV rows.
```

## Failure Cases

The agent handles the following failure cases with structured output:

### Dataset Not Found

Returned when the dataset registry has no matching dataset for the provided `dataset_id`.

Expected error type:

```text
DATASET_NOT_FOUND
```

### Missing Schema Profile

Returned when the dataset exists but no `schema_profile` is stored.

Expected error type:

```text
MISSING_SCHEMA_PROFILE
```

### Schema Context Build Failure

Returned when the schema context builder returns `None`, raises an exception, or returns an incomplete context.

Expected error type:

```text
SCHEMA_CONTEXT_BUILD_FAILED
```

## Dependency Injection Decision

The Data Profiler Agent uses dependency injection for:

```text
dataset_lookup_fn
schema_context_builder_fn
```

This allows tests to inject fake lookup/build functions without touching the real DuckDB registry.

This keeps the agent:

```text
modular
testable
decoupled from infrastructure
compatible with future orchestration
```

It also helps prove that the agent has no LLM dependency.

## Testing Coverage

The test suite covers:

```text
successful profiling/context response for a valid dataset_id
dataset not found
missing schema_profile
schema_context build failure
incomplete schema_context
structured output fields
no LLM dependency
compatibility with existing agent test style
```

The tests follow the existing backend testing approach and remain compatible with the project-root `pytest.ini`.

## Relationship to Text-to-SQL Agent

This Data Profiler Agent creates a necessary follow-up correction for the Text-to-SQL Agent.

The current Text-to-SQL Agent input allowed caller-provided `schema_context`. That is misleading for the real product design because the user should never provide schema context manually.

The planned correction is:

```text
Remove caller-provided schema_context from TextToSQLAgentInput.
Make schema_context an internal dependency resolved from dataset_id.
Do not call the LLM unless schema_context is successfully resolved.
```

After that correction, the Text-to-SQL Agent should accept only:

```text
dataset_id
question
request_id optional
metadata optional
```

This keeps the workflow secure and consistent:

```text
User provides dataset_id + question.
System resolves schema context internally.
Text-to-SQL uses trusted schema context.
SQL Validator validates generated SQL.
Query Executor runs only validated SQL.
```

## LangGraph Readiness

LangGraph is not introduced inside the Data Profiler Agent.

This follows the project architecture decision that individual agents should remain independently testable Python components, while LangGraph will later be used at the Supervisor Agent level for workflow orchestration.

The Data Profiler Agent is now ready to become a LangGraph node later because it has:

```text
typed input
typed output
deterministic behavior
structured failure states
no hidden LLM dependency
clear service-layer boundaries
```

## Current Implementation Summary

The Data Profiler Agent was implemented as a formal agent wrapper around the existing dataset registry and schema context builder services.

No existing profiling service logic was duplicated.

No raw rows are exposed.

No LLM call is made.

The agent now provides the missing architectural bridge between CSV upload/profiling and Text-to-SQL generation.

## Next Step

The next required architecture correction is to update the Text-to-SQL Agent so that `schema_context` is no longer accepted as caller-provided input.

After that correction is completed, the project can continue to the Query Executor Agent wrapper phase.
