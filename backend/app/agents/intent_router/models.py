from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class QueryIntent(str, Enum):
    ANALYTICS_QUERY = "analytics_query"
    VISUALIZATION_QUERY = "visualization_query"
    TABLE_PREVIEW_QUERY = "table_preview_query"
    DATA_QUALITY_QUERY = "data_quality_query"
    SCHEMA_QUESTION = "schema_question"
    UNSUPPORTED_QUERY = "unsupported_query"


class RoutingCapability(str, Enum):
    SQL_GENERATION = "sql_generation"
    SQL_VALIDATION = "sql_validation"
    QUERY_EXECUTION = "query_execution"
    RESULT_ANALYSIS = "result_analysis"

    CHART_SELECTION = "chart_selection"
    CHART_PAYLOAD_GENERATION = "chart_payload_generation"
    CHART_VALIDATION = "chart_validation"

    DATA_QUALITY_ANALYSIS = "data_quality_analysis"
    SCHEMA_PROFILING = "schema_profiling"

    ANSWER_FORMATTING = "answer_formatting"
    UNSUPPORTED_RESPONSE = "unsupported_response"
    MODEL_UNAVAILABLE_RESPONSE = "model_unavailable_response"


class RouterDecisionSource(str, Enum):
    RULE_BASED = "rule_based"
    LLM = "llm"
    HYBRID = "hybrid"
    FALLBACK = "fallback"
    DEPENDENCY_POLICY = "dependency_policy"


@dataclass(frozen=True)
class IntentRouterResult:
    primary_intent: QueryIntent
    required_capabilities: list[RoutingCapability]
    confidence: float
    reason: str
    source: RouterDecisionSource

    matched_signals: list[str] = field(default_factory=list)
    normalized_question: str = ""

    llm_used: bool = False
    needs_clarification: bool = False
    clarification_question: str | None = None

    is_routable: bool = True
    blocking_reason: str | None = None
    unsupported_reason: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_intent": self.primary_intent.value,
            "required_capabilities": [
                capability.value for capability in self.required_capabilities
            ],
            "confidence": self.confidence,
            "reason": self.reason,
            "source": self.source.value,
            "matched_signals": self.matched_signals,
            "normalized_question": self.normalized_question,
            "llm_used": self.llm_used,
            "needs_clarification": self.needs_clarification,
            "clarification_question": self.clarification_question,
            "is_routable": self.is_routable,
            "blocking_reason": self.blocking_reason,
            "unsupported_reason": self.unsupported_reason,
            "metadata": self.metadata,
        }


def build_required_capabilities(
    primary_intent: QueryIntent,
    supporting_intents: list[QueryIntent] | None = None,
) -> list[RoutingCapability]:
    """
    Maps the user's final goal into internal workflow capabilities.

    Important:
    visualization_query is a final response goal, not a shortcut.
    Normal visualization queries still require SQL generation, validation,
    execution, result analysis, and then chart generation.
    """

    supporting_intents = supporting_intents or []

    if primary_intent == QueryIntent.UNSUPPORTED_QUERY:
        return [
            RoutingCapability.UNSUPPORTED_RESPONSE,
            RoutingCapability.ANSWER_FORMATTING,
        ]

    if primary_intent == QueryIntent.VISUALIZATION_QUERY:
        if QueryIntent.DATA_QUALITY_QUERY in supporting_intents:
            return [
                RoutingCapability.DATA_QUALITY_ANALYSIS,
                RoutingCapability.CHART_SELECTION,
                RoutingCapability.CHART_PAYLOAD_GENERATION,
                RoutingCapability.CHART_VALIDATION,
                RoutingCapability.ANSWER_FORMATTING,
            ]

        if QueryIntent.SCHEMA_QUESTION in supporting_intents:
            return [
                RoutingCapability.SCHEMA_PROFILING,
                RoutingCapability.CHART_SELECTION,
                RoutingCapability.CHART_PAYLOAD_GENERATION,
                RoutingCapability.CHART_VALIDATION,
                RoutingCapability.ANSWER_FORMATTING,
            ]

        return [
            RoutingCapability.SQL_GENERATION,
            RoutingCapability.SQL_VALIDATION,
            RoutingCapability.QUERY_EXECUTION,
            RoutingCapability.RESULT_ANALYSIS,
            RoutingCapability.CHART_SELECTION,
            RoutingCapability.CHART_PAYLOAD_GENERATION,
            RoutingCapability.CHART_VALIDATION,
            RoutingCapability.ANSWER_FORMATTING,
        ]

    if primary_intent == QueryIntent.ANALYTICS_QUERY:
        return [
            RoutingCapability.SQL_GENERATION,
            RoutingCapability.SQL_VALIDATION,
            RoutingCapability.QUERY_EXECUTION,
            RoutingCapability.RESULT_ANALYSIS,
            RoutingCapability.ANSWER_FORMATTING,
        ]

    if primary_intent == QueryIntent.TABLE_PREVIEW_QUERY:
        return [
            RoutingCapability.SQL_VALIDATION,
            RoutingCapability.QUERY_EXECUTION,
            RoutingCapability.ANSWER_FORMATTING,
        ]

    if primary_intent == QueryIntent.DATA_QUALITY_QUERY:
        return [
            RoutingCapability.DATA_QUALITY_ANALYSIS,
            RoutingCapability.ANSWER_FORMATTING,
        ]

    if primary_intent == QueryIntent.SCHEMA_QUESTION:
        return [
            RoutingCapability.SCHEMA_PROFILING,
            RoutingCapability.ANSWER_FORMATTING,
        ]

    return [
        RoutingCapability.UNSUPPORTED_RESPONSE,
        RoutingCapability.ANSWER_FORMATTING,
    ]