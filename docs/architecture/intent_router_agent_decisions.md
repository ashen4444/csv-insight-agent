# Intent Router Agent — Architectural Decisions

## Purpose

This document records the main architectural and implementation decisions made during the development of the **Intent Router Agent** for the CSV Insight Agent project.

The Intent Router Agent is the first decision-making component in the agent workflow. Its responsibility is to classify incoming user requests and produce a structured routing decision that can later be used by the LangGraph Supervisor workflow.

---

## 1. Final-version agent implementation

The Intent Router Agent is implemented as part of the final production-style agent layer, not as a prototype or simple keyword wrapper.

The implementation goal is:

* enterprise-grade structure
* modular internal design
* testable behavior
* clear routing contracts
* future LangGraph compatibility
* safe handling of unsupported requests
* clear dependency behavior when the LLM/model is unavailable

---

## 2. LangGraph is not used inside the agent

Decision:

```text
Do not use LangGraph inside the Intent Router Agent.
```

Reason:

The agent should remain a focused Python component. LangGraph will be used later at the Supervisor/workflow level to orchestrate multiple agents.

Correct architecture:

```text
Intent Router Agent = focused routing component
LangGraph = workflow orchestration layer
```

Future workflow direction:

```text
START
  ↓
Intent Router Agent
  ↓
Conditional LangGraph routing
  ├── Analytics workflow
  ├── Visualization workflow
  ├── Data quality workflow
  ├── Schema/profile workflow
  └── Unsupported response workflow
```

---

## 3. Hybrid routing architecture

The Intent Router Agent is designed as a hybrid system.

Final architecture:

```text
Rule-based router
+ LLM-based semantic router
+ Hybrid decision layer
+ Confidence policy
+ Dependency policy
+ Unsupported request policy
```

The public workflow should call only:

```python
IntentRouterAgent.classify(question)
```

Internal components remain modular and independently testable.

---

## 4. Final router module structure

The final structure is:

```text
backend/app/agents/
├── __init__.py
├── intent_router_agent.py
└── intent_router/
    ├── __init__.py
    ├── models.py
    ├── rule_based_router.py
    ├── llm_based_router.py
    ├── hybrid_intent_router_agent.py
    ├── confidence_policy.py
    ├── dependency_policy.py
    └── unsupported_policy.py
```

The file name `llm_based_router.py` was selected instead of `llm_router.py` for clearer semantic meaning. The name `llm_router.py` could be confused with routing between different AI models based on task complexity.

---

## 5. Final intent categories

The agreed intent categories are:

```text
analytics_query
visualization_query
table_preview_query
data_quality_query
schema_question
unsupported_query
```

### analytics_query

Used for analytical questions that require SQL-based computation.

Examples:

```text
Average salary by country
Top 5 countries by average salary
Count employees by job title
Compare salary by experience level
```

### visualization_query

Used when the final user output should include a chart.

Examples:

```text
Show a bar chart of average salary by country
Plot salary by years of experience
Visualize job count by country
```

### table_preview_query

Used for simple row preview requests.

Examples:

```text
Show first 5 rows
Preview the dataset
Show sample records
```

### data_quality_query

Used for questions about reliability or problems in the dataset.

Examples:

```text
Are there missing values?
Find duplicate rows
Detect outliers
Which columns have invalid values?
```

### schema_question

Used for metadata and structure questions.

Examples:

```text
What columns are available?
What is the datatype of salary?
How many rows and columns are there?
Describe this dataset
```

### unsupported_query

Used for requests outside the CSV analytics system scope or unsafe operations.

Examples:

```text
Tell me a joke
Write an essay
Search the web
Send an email
Delete this dataset
```

---

## 6. Schema questions are separate from data quality questions

Decision:

```text
schema_question should not be grouped under data_quality_query.
```

Reason:

Schema questions ask about dataset structure and metadata.

Data quality questions ask about problems, reliability, or cleanliness.

Schema examples:

```text
What columns are in the dataset?
What is the datatype of salary?
How many rows and columns are there?
```

Data quality examples:

```text
Are there missing values?
Are there duplicate records?
Are there invalid values?
```

This separation keeps the future Data Profiler Agent and Data Quality Agent cleanly separated.

---

## 7. Primary intent and required capabilities are separate

The router should not return only one flat intent.

Final router output should include:

```text
primary_intent
required_capabilities
confidence
reason
source
matched_signals
llm_used
needs_clarification
clarification_question
is_routable
blocking_reason
unsupported_reason
metadata
```

Important decision:

```text
primary_intent = user's final response goal
required_capabilities = internal workflow steps needed to satisfy the request
```

This allows the router to express both what the user wants and what the system must do internally.

---

## 8. Visualization does not bypass analytics

Important correction:

```text
visualization_query does not mean go directly to the Chart Agent.
```

Example query:

```text
Show a chart of average salary by country
```

Correct routing:

```text
primary_intent = visualization_query
```

Required capabilities:

```text
sql_generation
sql_validation
query_execution
result_analysis
chart_selection
chart_payload_generation
chart_validation
answer_formatting
```

Correct workflow:

```text
Intent Router
→ Text-to-SQL Agent
→ SQL Validator Agent
→ Query Executor Agent
→ Result Analysis
→ Chart Agent
→ Answer Formatter Agent
```

Incorrect workflow:

```text
Intent Router
→ Chart Agent directly
```

Reason:

A chart must be built from analyzed query results. The Chart Agent should not bypass SQL generation, validation, or execution for normal analytics-based visualizations.

---

## 9. Rule-based router responsibility

The rule-based router handles clear and common CSV analytics requests without using an LLM.

It is responsible for:

* deterministic classification
* pattern matching
* matched signals
* confidence scoring
* matched intent metadata
* supporting intent detection
* ambiguity metadata
* unsupported request detection using the unsupported policy

The rule-based router is useful for predictable queries such as:

```text
Show first 5 rows
Average salary by country
Create a bar chart of average salary by country
Are there missing values?
What columns are available?
Delete this dataset
```

---

## 10. LLM-based router responsibility

The LLM-based router is used for semantic fallback when deterministic routing is uncertain or ambiguous.

It is triggered when:

```text
rule confidence is low
multiple intent groups compete
the rule-based result is too generic
the query wording is semantically complex
```

The LLM-based router must return structured JSON only.

It should not execute tools, generate SQL, run queries, or control the workflow directly.

Example LLM router output:

```json
{
  "primary_intent": "visualization_query",
  "supporting_intents": ["analytics_query"],
  "confidence": 0.94,
  "reason": "User wants a chart based on an aggregate analytics query.",
  "needs_clarification": false,
  "clarification_question": null,
  "unsupported_reason": null
}
```

---

## 11. Confidence policy

Confidence threshold logic is centralized in:

```text
confidence_policy.py
```

Reason:

Hardcoding thresholds inside multiple router files would make the system harder to tune and maintain.

The confidence policy decides:

```text
high confidence rule result → use rule result directly
low/medium confidence → try LLM fallback
accepted LLM result → use LLM route
weak LLM result → keep rule-based result
```

---

## 12. Dependency policy

Dependency validation is centralized in:

```text
dependency_policy.py
```

Reason:

The router must know whether the selected workflow can actually run.

Important production decision:

```text
If the workflow requires LLM-based SQL generation and the OpenAI/model API is unavailable, stop with a clear model-unavailable response.
```

Do not pretend the system can continue by only asking clarification questions.

Example:

```text
Average salary by country
```

This requires:

```text
sql_generation
```

If the model is unavailable, the router should produce:

```text
is_routable = false
blocking_reason = llm_required_but_model_unavailable
required_capabilities = model_unavailable_response, answer_formatting
```

However, deterministic workflows can still continue when they do not require the LLM.

Examples:

```text
Show first 5 rows
What columns are available?
Basic schema/profile questions
Some deterministic data-quality checks
```

---

## 13. Unsupported request policy

Unsupported request handling is centralized in:

```text
unsupported_policy.py
```

Unsupported requests should not be ignored, answered randomly, or passed into the analytics pipeline.

They should be routed as:

```text
primary_intent = unsupported_query
```

With an `unsupported_reason`.

Supported reason categories include:

```text
destructive_operation
external_web_request
external_communication_request
file_generation_request
non_csv_task
```

The most important general out-of-scope category is:

```text
non_csv_task
```

Examples:

```text
Tell me a joke
Explain Python decorators
Write my resume
Book a hotel
What is the weather today?
```

These should be handled as:

```text
primary_intent = unsupported_query
unsupported_reason = non_csv_task
```

---

## 14. Clarification behavior

The router supports clarification metadata:

```text
needs_clarification
clarification_question
```

Clarification is useful when the user query is unclear.

Example:

```text
Analyze salary
```

Possible clarification:

```text
I can analyze salary. Do you want average salary, salary distribution, salary by category, or a chart?
```

However, an important practical decision was made:

```text
If the LLM/model is unavailable and the workflow requires LLM-based SQL generation, return a clear model-unavailable message instead of asking fake clarification questions.
```

Reason:

Clarification alone does not solve the problem if the system still cannot generate SQL without the model.

---

## 15. Model availability behavior

The router includes model availability awareness.

If the selected workflow requires:

```text
sql_generation
```

and the model is unavailable, the system should stop safely.

Clear response purpose:

```text
The user should know the AI model/API needed for SQL generation is unavailable.
```

The system should not silently fail or pretend it can continue.

---

## 16. Audit and debugging metadata

The router output includes metadata to support debugging, testing, and future observability.

Useful metadata includes:

```text
matched_intents
supporting_intents
matched_signals
ambiguous
llm_fallback_attempted
llm_fallback_failed
llm_error
rule_based_result
llm_result
decision
model_available
dependency_policy_applied
unsupported_pattern
```

This will be useful later for:

```text
LangSmith tracing
OpenTelemetry logging
query audit logs
debugging incorrect routing
portfolio/interview explanation
```

---

## 17. Testing decisions

A dedicated test file was added:

```text
backend/tests/agents/test_intent_router_agent.py
```

The tests cover:

```text
analytics routing
visualization routing with analytics capabilities
table preview routing
schema question routing
data quality routing
data quality visualization routing
unsupported non-CSV tasks
unsupported destructive operations
model unavailable blocking
deterministic preview when model unavailable
result serialization
```

Important tested behavior:

```text
Show a bar chart of average salary by country
```

Must route as:

```text
primary_intent = visualization_query
```

But must include:

```text
sql_generation
sql_validation
query_execution
result_analysis
chart capabilities
```

---

## 18. Commit strategy decision

The Intent Router Agent implementation contains several architectural decisions.

Therefore, committing everything as one large commit is not ideal.

A better commit history separates decisions clearly:

```text
Define intent router domain models
Add unsupported request policy for CSV routing
Add rule-based intent routing
Add LLM-based fallback for semantic intent routing
Add routing confidence and dependency policies
Add hybrid intent router agent
Add intent router agent tests
```

This makes the repository history more professional and easier to explain in interviews.

---

## Final summary

The Intent Router Agent is designed as a production-oriented hybrid routing component for the CSV Insight Agent system.

It combines deterministic rule-based routing, LLM-based semantic fallback, confidence policy, dependency validation, unsupported request handling, and structured routing outputs.

Its most important architectural decision is the separation between:

```text
primary_intent
```

and:

```text
required_capabilities
```

This allows requests like visualization queries to be treated correctly as final output goals while still executing the necessary analytics workflow before chart generation.
