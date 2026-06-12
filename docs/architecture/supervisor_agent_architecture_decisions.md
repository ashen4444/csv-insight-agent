# Supervisor Agent v1 Architecture Decisions

## Status

Implemented, tested, and ready for commit.

## Agent Name

Supervisor Agent v1 with LangGraph Orchestration

## Implemented Files

```text
backend/app/agents/supervisor_agent.py
backend/tests/agents/test_supervisor_agent.py
backend/app/agents/__init__.py
```

## Purpose

The Supervisor Agent is the orchestration layer for the CSV Insight Agent multi-agent workflow.

Its responsibility is to connect the already implemented specialist agents into one controlled workflow. It does not replace the individual agents. Instead, it decides which agents should run, passes structured outputs from one agent to the next, stops the workflow when a blocking or failure state occurs, and returns a consistent final response through the Answer Formatter Agent.

Supervisor Agent v1 is the first production-style orchestration implementation for the backend agent layer.

## Core Architecture Decision

LangGraph is used only in the Supervisor Agent layer.

The individual agents remain normal Python classes/modules and stay independently testable.

```text
Agent = focused Python class/module
LangGraph = workflow orchestration layer
```

This keeps the system modular, testable, and easier to debug. Each agent can still be unit-tested without LangGraph, while the Supervisor can be tested as the workflow coordinator.

## Implemented Workflow

Supervisor Agent v1 supports the main analytics and visualization workflow:

```text
Intent Router Agent
→ Text-to-SQL Agent
→ SQL Validator / Guardrail Agent
→ Query Executor Agent
→ Data Quality Agent
→ Chart Agent
→ Answer Formatter Agent
```

The workflow is implemented as a LangGraph state graph with explicit nodes and conditional transitions.

The implemented LangGraph nodes are:

```text
route_intent
generate_sql
validate_sql
execute_query
evaluate_data_quality
build_chart
format_answer
```

## Supervisor Input Boundary

The Supervisor Agent accepts only safe public input:

```text
dataset_id
question
request_id optional
chart_generation_approved optional
approved_chart_type optional
metadata optional
```

The Supervisor intentionally does not accept trusted schema metadata from callers.

The following fields are intentionally not accepted:

```text
schema_context
schema_profile
table_name
allowed_columns
schema_context_override
```

Trusted schema context must be resolved internally by downstream agents from `dataset_id`.

## Trusted Metadata Rule

The Supervisor Agent follows the trusted metadata boundary used across the project.

User/API callers must not provide schema context, schema profile, table name, or allowed columns manually. Agents must resolve trusted dataset metadata internally from `dataset_id`.

This protects the system from caller-provided metadata injection and keeps the CSV privacy rule intact.

Raw CSV rows must not be sent to the LLM. The Text-to-SQL Agent remains responsible for resolving trusted schema context and sending only safe metadata to the SQL generation layer.

## Supervisor Output

The Supervisor Agent returns a structured `SupervisorAgentOutput`.

The output includes:

```text
success
dataset_id
question
final_response
workflow_status
executed_agents
skipped_agents
failed_agent optional
error_type optional
error_message optional
blocking_reason optional
execution_time_ms
metadata
```

The `final_response` field contains the serialized output from the Answer Formatter Agent.

This keeps the frontend integration simple because the API can return one consistent response structure while still preserving workflow-level debugging metadata.

## Workflow State Design

The LangGraph workflow state preserves upstream outputs for debugging and final answer formatting.

Important state fields include:

```text
dataset_id
question
request_id
chart_generation_approved
approved_chart_type
metadata

intent_router_output
text_to_sql_output
sql_validator_output
query_executor_output
data_quality_output
chart_agent_output
answer_formatter_input
answer_formatter_output

workflow_status
current_step
executed_agents
failed_agent
error_type
error_message
blocking_reason
supervisor_routing_blocked
```

The state is intentionally designed to preserve each agent's structured output instead of losing intermediate information.

## Mapping Decision

The Answer Formatter Agent intentionally accepts a flattened `AnswerFormatterAgentInput`.

Therefore, the Supervisor Agent is responsible for mapping upstream outputs into the flattened formatter input.

The Supervisor maps outputs from:

```text
IntentRouterResult
TextToSQLAgentOutput
SQLValidatorAgentOutput
QueryExecutorAgentOutput
DataQualityAgentOutput
ChartAgentOutput
```

into:

```text
AnswerFormatterAgentInput
```

This mapping is not placed inside the Answer Formatter Agent because the formatter should focus only on final response generation. It should not know how the LangGraph workflow state is organized.

## Early Stop Behavior

Supervisor Agent v1 stops downstream execution when an upstream agent blocks or fails.

The implemented early-stop rules are:

```text
Unsupported query → skip SQL generation and go directly to Answer Formatter
Needs clarification → skip SQL generation and go directly to Answer Formatter
Unroutable request → skip SQL generation and go directly to Answer Formatter
Text-to-SQL failure → skip validation, execution, data quality, and chart generation
SQL validation blocked/error → skip execution, data quality, and chart generation
Query execution failure → skip data quality and chart generation
Data quality blocked/failed → skip chart generation
Chart unavailable/failed → still format the table answer when execution and data quality succeeded
```

The Answer Formatter Agent is always called when possible so the frontend receives a consistent response.

## Supported Workflow Paths in v1

Supervisor Agent v1 fully supports:

```text
analytics_query
visualization_query
unsupported_query
needs_clarification
unroutable requests
```

For `analytics_query`, chart generation is not forced. The Chart Agent may return `chart_not_requested` and recommend a chart.

For `visualization_query`, the Supervisor enables chart generation because the user explicitly requested visualization.

## Conservative Handling of Unsupported Workflow Paths

Supervisor Agent v1 intentionally does not fully support these routes yet:

```text
schema_question
table_preview_query
dataset-level data_quality_query
```

These routes are blocked cleanly with a formatted response instead of pretending the workflow exists.

This is intentional because the current Answer Formatter Agent does not yet have dedicated flattened fields for schema-profile answers, table-preview responses, or dataset-level quality summaries.

Future versions should add those formatter fields and then route these intents properly.

## Chart Generation Decision

The system should not generate charts for every analytics query automatically.

Chart generation should happen when:

```text
the user explicitly asks for visualization
or chart generation is approved later
```

Supervisor Agent v1 passes `chart_generation_approved=True` to the Chart Agent when the router identifies a `visualization_query`.

For normal analytics queries, the Chart Agent can still recommend a chart but should not generate a chart payload unless the user requested or approved it.

## Failure Handling Decision

The Supervisor Agent does not hide failures.

When a node fails, the Supervisor preserves:

```text
failed_agent
error_type
error_message
blocking_reason
executed_agents
skipped_agents
```

This makes the workflow easier to debug and improves future observability/audit logging.

## Dependency Injection Decision

The Supervisor Agent supports dependency injection for all downstream agents:

```text
intent_router
text_to_sql_agent
sql_validator_agent
query_executor_agent
data_quality_agent
chart_agent
answer_formatter_agent
```

This allows the Supervisor to be tested using fake agents without real OpenAI calls, real DuckDB execution, or external services.

This keeps unit tests fast, deterministic, and safe.

## Test Coverage

The Supervisor Agent v1 test suite covers:

```text
successful analytics workflow
successful visualization workflow with chart payload
unsupported query stopping after routing
needs clarification stopping after routing
schema-question route blocked cleanly for v1
Text-to-SQL failure stopping validation/execution
SQL validation blocked stopping execution
query execution failure stopping data quality/chart
data quality blocked preventing chart generation
chart unavailable still returning table answer with warning
AnswerFormatterAgentInput mapping correctness
SupervisorAgentOutput.to_dict frontend-friendly serialization
```

All Supervisor Agent tests passed.

## Current Known Limitations

Supervisor Agent v1 is intentionally focused on the main analytics and visualization workflows.

Known limitations:

```text
schema_question is not fully routed through Data Profiler Agent yet
table_preview_query is not implemented as a dedicated workflow yet
dataset-level data_quality_query is not implemented yet
Supervisor is not yet integrated into the FastAPI query endpoint
Supervisor-level audit logging is not yet implemented
LangSmith/OpenTelemetry tracing is not yet implemented
```

These are future improvements, not defects in v1.

## Future Improvements

Recommended next improvements:

```text
1. Integrate SupervisorAgent into the FastAPI /query endpoint
2. Extend AnswerFormatterAgentInput for schema/profile responses
3. Route schema_question through DataProfilerAgent
4. Add table-preview workflow support
5. Add dataset-level data-quality workflow support
6. Add Supervisor-level audit logging
7. Add integration tests using real DuckDB and fake SQL generation
8. Add end-to-end API tests
9. Add observability with LangSmith or OpenTelemetry
10. Add frontend rendering for final_response, tables, charts, warnings, and recommendations
```

## Final Design Summary

Supervisor Agent v1 establishes the production orchestration layer for the CSV Insight Agent project.

It uses LangGraph for workflow control, keeps specialist agents independently testable, preserves each upstream output, performs the required mapping into the Answer Formatter Agent, stops safely on blocking states, and returns a consistent final response structure.

This creates the foundation for replacing manual API-level orchestration with a real multi-agent workflow.
