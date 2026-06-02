# Visualization Pipeline Testing

## Overview

This document records the implemented visualization pipeline behavior, supported chart generation scenarios, validation logic, and known limitations for the CSV Insight Agent backend.

---

# Current Visualization Pipeline

```text
User Question
    ↓
Visualization Intent Detection
    ↓
SQL Generation
    ↓
Query Execution
    ↓
Result Analysis
    ↓
Chart Selection
    ↓
Chart Payload Generation
    ↓
Chart Validation Warning
```

---

# Implemented Components

| Component                          | Responsibility                                           |
| ---------------------------------- | -------------------------------------------------------- |
| `visualization_intent_detector.py` | Detect explicit/generic visualization requests           |
| `result_analyzer.py`               | Analyze query result structure and recommend chart types |
| `chart_selector.py`                | Decide final chart type                                  |
| `chart_payload_builder.py`         | Build frontend-ready chart payload                       |
| `chart_validator.py`               | Generate chart mismatch warnings                         |

---

# Supported Visualization Types

| Chart Type   | Supported           |
| ------------ | ------------------- |
| Bar Chart    | Yes                 |
| Line Chart   | Yes                 |
| Scatter Plot | Yes                 |
| Metric Card  | Partial             |
| Pie Chart    | Not Implemented Yet |

---

# Visualization Intent Detection

## Explicit Visualization Requests

Examples:

```text
Generate a bar chart for average salary by country
Generate a scatter plot for years of experience and salary
Generate a line graph for salary trend by year
```

Expected behavior:

* `visualization_requested = true`
* `requested_chart_type` detected explicitly

---

## Generic Visualization Requests

Examples:

```text
Visualize average salary by country
Show a graph of employee bonus by department
```

Expected behavior:

* `visualization_requested = true`
* `requested_chart_type = null`
* Analyzer recommendation used later

---

## Non-Visualization Requests

Examples:

```text
Average salary by country
Show first 5 rows
List employee names
```

Expected behavior:

* `visualization_requested = false`
* Chart generation disabled

---

# Tested Scenarios

## Scenario 1 — Explicit Bar Chart

### Query

```json
{
  "dataset_id": "8d2b0bcd63ad",
  "question": "Generate a bar chart for average salary by country"
}
```

### Result

* Chart generated successfully
* Bar chart selected
* Payload generated correctly

---

## Scenario 2 — Generic Visualization Request

### Query

```json
{
  "dataset_id": "8d2b0bcd63ad",
  "question": "Visualize average salary by country"
}
```

### Result

* Analyzer recommended bar chart
* Chart payload generated successfully

---

## Scenario 3 — No Visualization Request

### Query

```json
{
  "dataset_id": "8d2b0bcd63ad",
  "question": "Average salary by country"
}
```

### Result

* Visualization disabled
* No chart payload generated

---

## Scenario 4 — Explicit Scatter Plot

### Query

```json
{
  "dataset_id": "8d2b0bcd63ad",
  "question": "Generate a scatter plot for years of experience and average salary"
}
```

### Result

* Scatter plot selected
* Numeric columns auto-detected
* Chart payload generated successfully

---

## Scenario 5 — Chart Mismatch Warning

### Query

```json
{
  "dataset_id": "8d2b0bcd63ad",
  "question": "Generate a line chart for years of experience and average salary"
}
```

### Result

* User-requested line chart honored
* Analyzer recommended scatter plot
* Validation warning generated successfully

---

# Current Validation Behavior

## Warning Types

| Warning Type                | Description                                              |
| --------------------------- | -------------------------------------------------------- |
| `chart_type_mismatch`       | User-selected chart differs from analyzer recommendation |
| `chart_payload_unavailable` | Payload generation failed                                |

---

# Known Limitations

## 1. Pie Charts Not Yet Implemented

Current system does not support:

* pie chart selection
* pie chart payload generation
* part-to-whole analysis

---

## 2. Multi-Series Charts Not Supported

Current payload builder only supports:

* single x-axis
* single y-axis

Not yet supported:

* grouped bar charts
* stacked charts
* multiple line series

---

## 3. No Frontend Rendering Yet

Current backend only generates chart metadata payloads.

Frontend rendering layer is not implemented yet.

---

## 4. Rule-Based Validation

Chart validation currently uses deterministic rule-based logic.

Future versions may introduce:

* LLM-assisted chart recommendations
* Visualization agents
* Intelligent chart repair suggestions

---

# Future Improvements

## Planned Enhancements

* Pie chart support
* Multi-series chart support
* Dashboard generation
* Visualization explanation agent
* Automatic chart repair suggestions
* Plotly/Recharts frontend integration
* Visualization quality scoring
* Intelligent aggregation recommendations

---

# Primary Testing Dataset

```text
Dataset ID: 8d2b0bcd63ad
```

Used for:

* visualization pipeline testing
* chart payload testing
* chart validation testing
* analyzer behavior testing

---
