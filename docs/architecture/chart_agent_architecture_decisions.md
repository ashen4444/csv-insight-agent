# Chart Agent Architecture Decisions

## Status

Implemented, tested, and ready for commit.

## Agent Name

Chart Agent

## Implemented Files

```text
backend/app/agents/chart_agent.py
backend/tests/agents/test_chart_agent.py
backend/app/agents/__init__.py
```

## Purpose

The Chart Agent is responsible for deciding whether chart generation should proceed after a query has already been executed and evaluated for data quality.

Its purpose is to act as the chart-generation boundary between the executed query result and the future Answer Formatter Agent, Supervisor Agent, and frontend visualization layer.

The Chart Agent does not generate SQL, validate SQL, execute SQL, clean data, or format the final natural-language answer. It only works with structured upstream outputs and produces a structured chart-generation result.

## Design Decision: Agent Wraps Existing Chart Services

The Chart Agent does not duplicate visualization intent detection, result analysis, chart selection, chart payload construction, or chart validation logic.

It wraps the existing service-layer functions:

```text
backend/app/services/visualization_intent_detector.py
backend/app/services/result_analyzer.py
backend/app/services/chart_selector.py
backend/app/services/chart_payload_builder.py
backend/app/services/chart_validator.py
```

This keeps the architecture clean:

```text
Service layer = deterministic chart-related logic
Chart Agent = structured orchestration boundary around chart services
Supervisor Agent = future LangGraph workflow orchestration
```

This follows the same wrapper pattern used by the previously implemented agents.

## Design Decision: No LangGraph Inside the Agent

The Chart Agent is implemented as a focused Python agent class.

LangGraph is not used inside the Chart Agent.

The intended architecture remains:

```text
Agent = focused Python module/class
LangGraph = workflow orchestration layer
```

The Chart Agent is independently testable and can later be called as a node inside the Supervisor Agent workflow.

## Design Decision: Chart Generation Is Not Automatic

The system should not generate charts for every analytical query.

The Chart Agent only attempts chart generation when:

```text
1. The user explicitly requests a chart or visualization.
2. A chart recommendation was previously produced and the user approves chart generation.
```

For example, a normal analytical question such as:

```text
Average salary by country
```

may produce a chart recommendation, but the Chart Agent should return a non-generating status unless visualization intent or explicit approval exists.

A user request such as:

```text
Generate a bar chart of average salary by country
Visualize average salary by country
Show this as a scatter plot
```

can trigger chart generation if the executed result and quality checks allow it.

## Design Decision: Respect Data Quality Agent Output

The Chart Agent consumes Data Quality Agent fields where available.

Chart generation is blocked when the data-quality result indicates that the executed query result is not safe or useful for visualization.

Blocking conditions include:

```text
quality_failed
quality_not_evaluated
is_result_usable=False
is_result_empty=True
is_result_too_large=True
critical visualization warnings
```

Non-critical visualization warnings can still allow chart generation, but the Chart Agent returns a warning so downstream components can explain the limitation to the user.

This keeps misleading or low-quality charts from being generated silently.

## Design Decision: Unsupported Payload Types Return chart_unavailable

The existing visualization intent detector can identify chart/display requests such as:

```text
bar_chart
line_chart
scatter_plot
metric_card
table
```

The current chart payload builder supports only:

```text
bar_chart
line_chart
scatter_plot
```

The Chart Agent therefore treats unsupported payload types such as `metric_card` and `table` as unavailable rather than failed.

This means the agent returns a structured unavailable status instead of treating the system as broken.

The selected behavior is:

```text
Unsupported chart/display payload type = chart_unavailable
Internal service error = chart_failed
Upstream execution or data-quality block = chart_blocked
```

This distinction is important for the future Answer Formatter Agent because the user-facing response should be different for each case.

## Design Decision: Keep Metric Cards and Tables as Future Service Enhancements

The Chart Agent wrapper phase does not modify `chart_payload_builder.py`.

Metric card and table payload support should be added later as a separate service-layer enhancement if needed.

This keeps the current phase focused on implementing the agent boundary without mixing it with feature expansion.

Future service enhancements may include:

```text
metric_card payload support
frontend table payload support
Plotly-compatible chart specs
richer chart metadata
multi-series chart support
```

## Design Decision: Frontend-Friendly Payload, Not Image Generation

The Chart Agent returns structured chart payload data.

It does not generate image files.

It does not use Matplotlib.

It does not render charts in the backend.

The frontend can later use the structured payload to render charts using Plotly or another frontend visualization library.

This keeps the backend responsible for chart decision-making and payload construction, while the frontend remains responsible for visual rendering.

## Design Decision: Structured Statuses for Downstream Agents

The Chart Agent returns explicit chart-generation statuses so the future Answer Formatter Agent and Supervisor Agent can make clear decisions.

The implemented statuses are:

```text
chart_generated
chart_generated_with_warning
chart_not_requested
chart_blocked
chart_unavailable
chart_failed
```

These statuses make it easy to distinguish between:

```text
a chart was successfully generated
a chart was generated but includes warnings
a chart was not requested
a chart was requested but blocked by upstream/data-quality conditions
a chart was requested but no supported payload could be built
a chart failed because of a technical/service error
```

## Design Decision: Structured Errors

The Chart Agent returns structured error types instead of only plain error strings.

Implemented error types include:

```text
upstream_execution_not_successful
invalid_result_payload
data_quality_blocked
result_not_visualizable
chart_payload_unavailable
chart_service_unavailable
invalid_service_response
unexpected_chart_error
```

This improves auditability, testability, and future orchestration behavior.

## Design Decision: Strict Input Boundary

The Chart Agent input accepts structured upstream execution and data-quality information.

It does not accept caller-provided trusted dataset metadata such as:

```text
schema_context
schema_profile
schema_context_override
table_name
allowed_columns
```

This keeps the trusted metadata rule consistent across the system.

The Chart Agent does not need to resolve schema context directly because it operates on already-executed query results and Data Quality Agent output.

## Design Decision: Pydantic Models With Forbidden Extra Fields

The Chart Agent follows the same production-style wrapper pattern used by previous agents.

The implementation uses:

```python
model_config = ConfigDict(extra="forbid")
```

This prevents accidental or unsafe caller-provided fields from entering the agent boundary.

The main models are:

```text
ChartAgentInput
ChartAgentOutput
ChartWarning
```

The main enums are:

```text
ChartGenerationStatus
ChartAgentErrorType
ChartWarningSeverity
```

## Design Decision: Dependency Injection for Testability

The Chart Agent supports dependency injection for its wrapped services.

Injectable dependencies include:

```text
visualization_intent_detector
result_analyzer
chart_selector
chart_payload_builder
chart_validator
```

This allows unit tests to simulate invalid service responses, service failures, unsupported payloads, and warning behavior without changing the real service layer.

## Design Decision: Serialization Support

The Chart Agent output includes a `to_dict()` method.

This method uses Pydantic JSON-mode serialization so enums are converted into JSON-friendly string values.

This keeps the output suitable for:

```text
FastAPI responses
Supervisor Agent state
Answer Formatter Agent input
audit/debug logs
frontend chart rendering
```

## Tested Scenarios

The Chart Agent test suite covers:

```text
explicit chart request
not-requested chart with recommendation
approved chart generation after recommendation
upstream execution failure
data-quality blocked result
empty result blocking
large result blocking
unsupported metric card payload
requested chart type mismatch warning
non-critical visualization warning
critical visualization warning
invalid visualization intent response
invalid result analyzer response
invalid chart selector response
invalid chart validator response
invalid result payload row-count mismatch
to_dict serialization
extra input field rejection
```

## Final Architectural Summary

The Chart Agent is now the production-style wrapper around the existing chart service layer.

It respects visualization intent, does not generate charts automatically, consumes Data Quality Agent output, blocks misleading or unsafe chart generation, and returns structured chart-generation results for future workflow orchestration.

The implementation keeps chart rendering separate from backend logic and prepares the project for the next agent phase: the Answer Formatter Agent.

## Next Step

The next implementation phase should be:

```text
Answer Formatter Agent
```

The Answer Formatter Agent will consume structured outputs from upstream agents, including:

```text
Intent Router Agent
Text-to-SQL Agent
SQL Validator / Guardrail Agent
Query Executor Agent
Data Quality Agent
Chart Agent
```

Its responsibility will be to produce the final user-facing response while preserving structured metadata for audit/debugging and frontend use.
