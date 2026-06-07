# Answer Formatter Agent Architecture Decisions

## Status

Implemented, tested, and ready for commit.

## Agent Name

Answer Formatter Agent

## Implemented Files

```text
backend/app/agents/answer_formatter_agent.py
backend/tests/agents/test_answer_formatter_agent.py
backend/app/agents/__init__.py
```

## Purpose

The Answer Formatter Agent is responsible for converting structured upstream agent outputs into the final user-facing response object.

It is the final response-preparation layer before the FastAPI response, future frontend rendering, and future Supervisor/LangGraph orchestration output.

The agent does not perform analytics logic itself. It formats the result of previous workflow steps into a clean, structured, frontend-friendly response.

## Agent Role

The Answer Formatter Agent consumes already-structured workflow output such as routing decisions, generated SQL status, SQL validation status, query execution results, data-quality checks, and chart-generation status.

Its responsibilities are:

* decide the final response status,
* decide the final response type,
* prepare a clear user-facing message,
* expose display-ready table records,
* expose chart payloads only when available,
* include warnings and recommendations,
* preserve technical details for debugging/audit use,
* avoid hiding upstream failures or blocking reasons.

## Non-Responsibilities

The Answer Formatter Agent must not:

* generate SQL,
* validate SQL,
* execute SQL,
* clean or mutate data,
* generate chart payloads,
* render chart images,
* call LangGraph internally,
* call an LLM,
* accept trusted schema context from the caller,
* silently hide upstream failures.

These responsibilities remain assigned to their dedicated agents or services.

## Design Decision: Deterministic Template-Based Formatter

The Answer Formatter Agent is implemented as a deterministic, template-based formatter.

No LLM call is used.

This decision keeps the formatter:

* predictable,
* testable,
* fast,
* privacy-safe,
* easy to debug,
* compatible with FastAPI and frontend rendering.

Because upstream agents already provide structured statuses, warnings, blocking reasons, and metadata, an LLM is not needed at this layer.

## Design Decision: Flattened Input Model

The formatter accepts a flattened `AnswerFormatterAgentInput` instead of full upstream agent objects.

This allows the agent to work with:

* serialized `.to_dict()` outputs,
* future LangGraph workflow state,
* FastAPI response-building code,
* unit tests,
* frontend-compatible response preparation.

The formatter intentionally does not depend directly on previous agent classes.

This avoids tight coupling between the final response layer and each upstream agent implementation.

## Design Decision: Supervisor/LangGraph Owns Upstream Mapping

The Answer Formatter Agent does not map full upstream agent outputs into formatter input by itself.

The future Supervisor Agent / LangGraph orchestration layer will be responsible for converting:

```text
IntentRouterResult.to_dict()
TextToSQLAgentOutput.to_dict()
SQLValidatorAgentOutput.to_dict()
QueryExecutorAgentOutput.to_dict()
DataQualityAgentOutput.to_dict()
ChartAgentOutput.to_dict()
```

into:

```text
AnswerFormatterAgentInput
```

This keeps the formatter focused on one responsibility: formatting a structured response.

The mapping logic belongs in the workflow orchestration layer because it knows which upstream agents actually ran for each intent.

## Design Decision: Frontend-Friendly Output Structure

The formatter returns a structured output instead of a plain text string.

The final response includes:

```text
success
dataset_id
question
response_status
response_type
message
summary
display_results
display_result_count
display_columns
chart_available
chart_type
chart_payload
warnings
recommendations
technical_details
error_type
error_message
blocking_reason
metadata
```

This structure is designed for future frontend rendering where different fields can be shown in different UI sections:

* main answer message,
* result table,
* chart area,
* warning banners,
* recommendation cards,
* debug/audit panel.

## Design Decision: Response Status Enum

The formatter uses `AnswerResponseStatus` to clearly describe the final state of the workflow.

Supported statuses are:

```text
answer_ready
answer_ready_with_warning
no_results
blocked
failed
unsupported
needs_clarification
```

This makes the final response easier to consume by the frontend and future Supervisor Agent.

## Design Decision: Response Type Enum

The formatter uses `AnswerResponseType` to describe how the frontend should display the answer.

Supported response types are:

```text
text_answer
table_answer
chart_answer
text_with_table
text_with_chart
text_with_table_and_chart
error_message
clarification_message
unsupported_message
```

This separates the workflow result status from the display strategy.

## Design Decision: Do Not Hide Upstream Failures

The formatter checks upstream failure and blocking states in order.

Important handled cases include:

* unsupported query,
* clarification needed,
* unroutable request,
* SQL generation failure,
* SQL validation blocked,
* SQL validation failure,
* query execution blocked,
* query execution failure,
* data-quality blocked result,
* data-quality failure,
* chart unavailable,
* chart blocked,
* chart failed.

The formatter does not pretend the workflow succeeded when an upstream agent failed or blocked the request.

## Design Decision: SQL Validation Blocks Are User-Visible

If SQL validation returns a blocked or unsafe state, the formatter returns a blocked response.

This is important because validation failures represent safety or correctness guardrails.

For example, unsafe SQL, invalid SQL, unsupported SQL shapes, or schema-mismatch issues should be shown as a clear blocked response rather than hidden behind a generic error.

## Design Decision: Query Execution Failures Are User-Visible

If the Query Executor Agent reports execution failure or blocked execution, the formatter returns a failed or blocked response.

The formatter avoids showing stale, empty, or misleading result tables when execution did not succeed.

## Design Decision: Data Quality Can Block Final Display

If the Data Quality Agent marks the result as not usable, the formatter blocks the final display.

This ensures that results with critical quality issues are not presented as trustworthy answers.

Non-critical warnings are still included while allowing the answer to be shown.

## Design Decision: Preserve Data Quality Warnings and Recommendations

The formatter converts Data Quality Agent warnings and recommendations into normalized answer-level warning and recommendation objects.

This allows the frontend to show warnings and recommendations consistently regardless of their original upstream source.

The formatter preserves warning metadata for debugging and audit use.

## Design Decision: Chart Payload Is Included Only When Available

The formatter includes `chart_payload` only when the Chart Agent successfully produced one.

A chart is considered available only when:

```text
is_chart_available=True
chart_payload is not None
chart_generation_status is chart_generated or chart_generated_with_warning
```

The formatter does not imply that a chart exists when the Chart Agent returned:

```text
chart_not_requested
chart_blocked
chart_unavailable
chart_failed
```

This prevents the frontend from trying to render a missing chart.

## Design Decision: Chart Not Requested Can Still Produce Recommendation

If a chart is recommended but not requested, the formatter does not generate or expose a chart payload.

Instead, it can include a recommendation such as:

```text
A bar_chart may help visualize this result, but no chart was generated because the user did not request one.
```

This preserves the project rule that charts should not be generated automatically for every query.

## Design Decision: Chart Unavailable Is a Warning, Not a Full Answer Failure

When the main query result is successful but chart generation is unavailable, the formatter can still return a successful answer with warnings.

This allows the user to see the table result even if a chart could not be generated.

The formatter clearly states that the chart was requested but could not be generated.

## Design Decision: Trusted Metadata Is Not Accepted From Caller

The Answer Formatter Agent does not accept caller-provided trusted metadata such as:

```text
schema_context
schema_profile
schema_context_override
table_name
allowed_columns
```

This follows the project-wide trusted metadata rule.

The formatter does not need schema context directly because upstream agents already performed trusted schema resolution, validation, execution, data-quality checks, and chart preparation.

## Design Decision: Technical Details Are Separated From User Message

The formatter separates user-facing content from technical details.

User-facing fields:

```text
message
summary
display_results
chart_payload
warnings
recommendations
```

Debug/audit fields:

```text
technical_details
metadata
error_type
error_message
blocking_reason
```

This avoids exposing unnecessary implementation details in the main response while still preserving useful diagnostic information.

## Design Decision: Serialization Support

`AnswerFormatterAgentOutput` includes a `to_dict()` method using:

```python
model_dump(mode="json")
```

This keeps enum values serialized as strings and makes the output suitable for:

* FastAPI JSON responses,
* frontend display,
* audit logs,
* future LangGraph state serialization,
* tests.

## Implemented Models

The Answer Formatter Agent introduced:

```text
AnswerFormatterAgentInput
AnswerFormatterAgentOutput
AnswerResponseStatus
AnswerResponseType
AnswerFormatterErrorType
AnswerWarning
AnswerWarningSeverity
AnswerRecommendation
AnswerRecommendationPriority
```

## Implemented Public Methods

The agent exposes:

```text
format(...)
generate_response(...)
```

`format(...)` delegates to `generate_response(...)`.

This keeps the method name readable while allowing future internal expansion if needed.

## Test Coverage

The unit tests cover:

* successful table answer,
* answer with data-quality warning,
* no-results response,
* unsupported query,
* clarification response,
* SQL validation blocked response,
* query execution failed response,
* data-quality blocked response,
* generated chart payload,
* chart unavailable without pretending chart exists,
* chart recommendation when chart was not requested,
* enum serialization through `to_dict()`,
* rejection of caller-provided trusted schema context.

## Final Design Summary

The Answer Formatter Agent completes the final response-preparation layer of the current multi-agent workflow.

It is deterministic, frontend-friendly, audit-friendly, independently testable, and ready for future Supervisor/LangGraph orchestration.

The agent correctly preserves upstream statuses and avoids mixing responsibilities with routing, SQL generation, validation, execution, data quality evaluation, or chart generation.
