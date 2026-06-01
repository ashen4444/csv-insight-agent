# Query Intent Misinterpretation Observation

## Overview

During testing of the LLM-powered Text-to-SQL pipeline in the CSVInsight Agent project, an important semantic interpretation issue was observed.

The system successfully generated syntactically valid SQL queries and executed them safely inside DuckDB. However, the generated query did not fully capture the analytical intent of the user’s natural language question.

---

# Test Scenario

## Dataset

Tested using:

```text
AI_Impact_on_Jobs_2030.csv
```

The dataset contained approximately 3000 rows with repeated job titles such as:

* Data Scientist
* Data Engineer
* DevOps Engineer
* HR Specialist

Multiple records represented the same job category.

---

# User Question

```text
How many jobs are mentioned in this dataset?
```

---

# Generated SQL

```sql
SELECT COUNT(*) FROM "ai_impact_on_jobs_2030_7b3a084dbc3a";
```

---

# System Response

```json
{
  "count_star()": 3000
}
```

---

# Problem Analysis

The generated SQL query counted the total number of rows in the dataset instead of counting the number of unique job titles.

The LLM interpreted the phrase:

```text
"How many jobs"
```

as:

```text
"How many records"
```

rather than:

```text
"How many unique job categories"
```

This demonstrates a semantic intent interpretation limitation in the current Text-to-SQL pipeline.

---

# Expected Analytical Interpretation

A more semantically accurate SQL query would have been:

```sql
SELECT COUNT(DISTINCT "Job_Title")
FROM "ai_impact_on_jobs_2030_7b3a084dbc3a";
```

This query would count unique job titles instead of total dataset rows.

---

# Key Observation

The current system demonstrates:

* strong SQL syntax generation
* safe query generation
* reliable local execution
* schema-aware prompting

However, it still lacks a dedicated analytical intent understanding layer.

The system currently focuses on:

```text
Natural Language → Valid SQL
```

instead of:

```text
Natural Language → Semantic Intent → Analytical SQL
```

---

# Architectural Insight

This observation suggests that production-grade Text-to-SQL systems require more than basic prompt-based SQL generation.

Future improvements may include:

* intent classification
* analytical query understanding
* semantic query rewriting
* domain-aware prompting
* query planning agents
* intelligent aggregation selection

---

# Proposed Future Enhancement

A future architecture improvement may introduce a dedicated:

```text
Query Intent Agent
```

Responsibilities may include:

* distinguishing between row counts and unique entity counts
* identifying analytical intent
* detecting aggregation semantics
* rewriting ambiguous user questions
* improving SQL generation reliability

Example:

```text
"How many jobs are mentioned?"
```

could first be transformed into:

```text
"How many unique job titles exist?"
```

before SQL generation.

---

# Engineering Importance

This observation is valuable because it highlights a real-world challenge in enterprise Text-to-SQL systems:

```text
Generating valid SQL is easier than understanding analytical intent.
```

The issue is not a database execution failure or syntax problem. Instead, it is an intelligence-layer limitation related to semantic interpretation and business meaning understanding.

---

# Current Project Status

At the current development stage, the system intentionally prioritizes:

* backend stability
* safe SQL execution
* schema-aware prompting
* validation architecture
* local-first privacy protection

before introducing more advanced intelligent query planning layers.

This staged development approach keeps the platform stable while progressively increasing intelligence capabilities.
