# SQL Generation Semantic Limitation

## Observation

The current Text-to-SQL pipeline validates SQL structure and schema safety correctly, but the LLM may still generate semantically incomplete queries when the user requests non-existent columns.

Example user question:

```text
Show employee_bonus by country
```

Generated SQL:

```sql
SELECT "Country"
FROM "ai_impact_on_jobs_2030_47d7dd3144f7"
LIMIT 100
```

The LLM silently ignored the non-existent `employee_bonus` field and generated a partially relevant query instead of returning an error or clarification response.

---

## Current System Behavior

The current validation layer correctly verifies:

* valid SQL syntax
* allowed SQL operations
* real table references
* real schema column references
* safe execution constraints

However, validation only checks whether the generated SQL is structurally safe and schema-valid.

It does NOT verify whether the generated SQL fully satisfies the semantic intent of the user's natural language question.

---

## Root Cause

This is not a SQL validation issue.

The problem originates from the SQL generation stage where the LLM attempts to recover from unknown schema references by generating a partially valid query.

---

## Why This Is Deferred

This issue belongs to a future phase focused on:

* semantic query understanding
* schema-term alignment
* clarification workflows
* SQL generation reliability
* hallucination-aware query generation

Implementing semantic intent verification now would significantly increase system complexity and is outside the current execution safety phase.

---

## Current Priority

Current project focus remains:

* execution safety
* query constraints
* stable result handling
* backend reliability
* production-safe SQL execution

---

## Potential Future Improvements

Possible future solutions include:

* schema-aware entity extraction
* required-field verification
* semantic SQL validation
* clarification prompts for missing columns
* retrieval-augmented schema matching
* multi-stage SQL generation verification
* LLM self-checking before execution
