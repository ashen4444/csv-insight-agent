from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.agents.intent_router.models import (
    IntentRouterResult,
    QueryIntent,
    RouterDecisionSource,
    build_required_capabilities,
)
from app.agents.intent_router.unsupported_policy import UnsupportedPolicy


@dataclass(frozen=True)
class IntentPattern:
    signal: str
    pattern: str


class RuleBasedIntentRouter:
    """
    Deterministic routing layer.

    Handles clear, common CSV analytics requests without using an LLM.
    Produces confidence, matched signals, matched intents, and ambiguity metadata.
    """

    INTENT_PRIORITY: list[QueryIntent] = [
        QueryIntent.UNSUPPORTED_QUERY,
        QueryIntent.VISUALIZATION_QUERY,
        QueryIntent.DATA_QUALITY_QUERY,
        QueryIntent.SCHEMA_QUESTION,
        QueryIntent.TABLE_PREVIEW_QUERY,
        QueryIntent.ANALYTICS_QUERY,
    ]

    PATTERNS: dict[QueryIntent, list[IntentPattern]] = {
        QueryIntent.VISUALIZATION_QUERY: [
            IntentPattern(
                "explicit_chart_request",
                r"\b(chart|graph|plot|visuali[sz]e|dashboard)\b",
            ),
            IntentPattern(
                "specific_chart_type",
                r"\b(bar|line|pie|scatter|histogram|heatmap|area)\s+(chart|graph|plot)\b",
            ),
            IntentPattern(
                "visual_comparison_request",
                r"\b(compare|comparison)\b.*\b(visually|chart|graph|plot)\b",
            ),
            IntentPattern(
                "draw_chart_request",
                r"\b(draw|show|create|generate)\b.*\b(chart|graph|plot)\b",
            ),
        ],
        QueryIntent.TABLE_PREVIEW_QUERY: [
            IntentPattern(
                "first_n_rows_request",
                r"\b(first|top)\s+\d+\s+(rows|records)\b",
            ),
            IntentPattern(
                "preview_request",
                r"\b(preview|sample|head)\b",
            ),
            IntentPattern(
                "show_rows_request",
                r"\b(show|display|list)\b.*\b(rows|records)\b",
            ),
            IntentPattern(
                "show_raw_data_request",
                r"\bshow\s+me\s+the\s+(data|dataset|csv)\b",
            ),
        ],
        QueryIntent.DATA_QUALITY_QUERY: [
            IntentPattern(
                "missing_values_request",
                r"\b(missing|null|nan|empty)\s*(values|data|cells|fields)?\b",
            ),
            IntentPattern(
                "duplicate_records_request",
                r"\bduplicates?|duplicate\s+(rows|records|values)\b",
            ),
            IntentPattern(
                "outlier_detection_request",
                r"\boutliers?|anomalies|anomaly\b",
            ),
            IntentPattern(
                "invalid_values_request",
                r"\binvalid\s+(values|records|data|formats?)\b",
            ),
            IntentPattern(
                "inconsistent_data_request",
                r"\binconsistent\s+(values|data|formats?|categories)\b",
            ),
            IntentPattern(
                "data_quality_request",
                r"\bdata\s+quality|cleanliness|dirty\s+data|quality\s+issues\b",
            ),
        ],
        QueryIntent.SCHEMA_QUESTION: [
            IntentPattern(
                "column_list_request",
                r"\b(columns?|fields?|headers?)\b",
            ),
            IntentPattern(
                "data_type_request",
                r"\b(data\s+type|datatype|type)\b",
            ),
            IntentPattern(
                "schema_request",
                r"\b(schema|metadata|structure)\b",
            ),
            IntentPattern(
                "dataset_description_request",
                r"\b(describe|summarize|profile)\b.*\b(dataset|csv|data)\b",
            ),
            IntentPattern(
                "shape_request",
                r"\b(rows?\s+and\s+columns?|shape|dimensions?)\b",
            ),
        ],
        QueryIntent.ANALYTICS_QUERY: [
            IntentPattern(
                "aggregation_request",
                r"\b(avg|average|mean|median|sum|total|count|min|max|minimum|maximum)\b",
            ),
            IntentPattern(
                "ranking_request",
                r"\b(highest|lowest|largest|smallest|top|bottom|most|least)\b",
            ),
            IntentPattern(
                "grouping_request",
                r"\b(group|grouped|breakdown|distribution|frequency)\b",
            ),
            IntentPattern(
                "comparison_request",
                r"\b(compare|comparison|versus|vs)\b",
            ),
            IntentPattern(
                "trend_request",
                r"\btrend|over\s+time|yearly|monthly|weekly|daily\b",
            ),
            IntentPattern(
                "relationship_request",
                r"\brelationship|correlation|impact|effect|between\b",
            ),
            IntentPattern(
                "by_dimension_request",
                r"\bby\s+[a-zA-Z_][a-zA-Z0-9_ ]*\b",
            ),
            IntentPattern(
                "analytics_verbs_request",
                r"\b(analyze|analyse|analysis|insight|insights)\b",
            ),
            IntentPattern(
                "distinct_values_request",
                r"\b(unique|distinct)\b",
            ),
            IntentPattern(
                "how_many_request",
                r"\bhow\s+many\b",
            ),
        ],
    }

    def __init__(
        self,
        unsupported_policy: UnsupportedPolicy | None = None,
    ) -> None:
        self.unsupported_policy = unsupported_policy or UnsupportedPolicy()

    def classify(self, question: str) -> IntentRouterResult:
        normalized_question = self._normalize_question(question)

        if not normalized_question:
            return IntentRouterResult(
                primary_intent=QueryIntent.UNSUPPORTED_QUERY,
                required_capabilities=build_required_capabilities(
                    QueryIntent.UNSUPPORTED_QUERY
                ),
                confidence=1.0,
                reason="Question is empty or invalid.",
                source=RouterDecisionSource.RULE_BASED,
                normalized_question=normalized_question,
                unsupported_reason="non_csv_task",
                metadata={
                    "matched_intents": [],
                    "supporting_intents": [],
                    "ambiguous": False,
                },
            )

        unsupported_match = self.unsupported_policy.classify(normalized_question)

        if unsupported_match is not None:
            return IntentRouterResult(
                primary_intent=QueryIntent.UNSUPPORTED_QUERY,
                required_capabilities=build_required_capabilities(
                    QueryIntent.UNSUPPORTED_QUERY
                ),
                confidence=0.98,
                reason="Question is outside the supported CSV analytics scope.",
                source=RouterDecisionSource.RULE_BASED,
                matched_signals=[unsupported_match.signal],
                normalized_question=normalized_question,
                unsupported_reason=unsupported_match.reason.value,
                metadata={
                    "matched_intents": [QueryIntent.UNSUPPORTED_QUERY.value],
                    "supporting_intents": [],
                    "ambiguous": False,
                    "unsupported_pattern": unsupported_match.pattern,
                },
            )

        matches_by_intent = self._match_all_intents(normalized_question)
        selected_intent = self._select_intent(matches_by_intent)

        matched_signals = matches_by_intent.get(selected_intent, [])
        matched_intents = [
            intent for intent, signals in matches_by_intent.items() if signals
        ]

        supporting_intents = [
            intent for intent in matched_intents if intent != selected_intent
        ]

        confidence = self._calculate_confidence(
            selected_intent=selected_intent,
            matched_signals=matched_signals,
            matched_intents=matched_intents,
            normalized_question=normalized_question,
        )

        source = (
            RouterDecisionSource.RULE_BASED
            if matched_signals
            else RouterDecisionSource.FALLBACK
        )

        return IntentRouterResult(
            primary_intent=selected_intent,
            required_capabilities=build_required_capabilities(
                primary_intent=selected_intent,
                supporting_intents=supporting_intents,
            ),
            confidence=confidence,
            reason=self._build_reason(
                selected_intent=selected_intent,
                matched_signals=matched_signals,
                matched_intents=matched_intents,
            ),
            source=source,
            matched_signals=matched_signals,
            normalized_question=normalized_question,
            metadata={
                "matched_intents": [intent.value for intent in matched_intents],
                "supporting_intents": [
                    intent.value for intent in supporting_intents
                ],
                "ambiguous": self._is_ambiguous(matched_intents),
            },
        )

    def _match_all_intents(
        self,
        normalized_question: str,
    ) -> dict[QueryIntent, list[str]]:
        return {
            intent: self._match_patterns(normalized_question, patterns)
            for intent, patterns in self.PATTERNS.items()
        }

    def _select_intent(
        self,
        matches_by_intent: dict[QueryIntent, list[str]],
    ) -> QueryIntent:
        for intent in self.INTENT_PRIORITY:
            if matches_by_intent.get(intent):
                return intent

        return QueryIntent.ANALYTICS_QUERY

    def _calculate_confidence(
        self,
        selected_intent: QueryIntent,
        matched_signals: list[str],
        matched_intents: list[QueryIntent],
        normalized_question: str,
    ) -> float:
        if selected_intent == QueryIntent.UNSUPPORTED_QUERY and matched_signals:
            return 0.98

        if not matched_signals:
            return 0.55

        base_confidence = {
            QueryIntent.VISUALIZATION_QUERY: 0.84,
            QueryIntent.DATA_QUALITY_QUERY: 0.86,
            QueryIntent.SCHEMA_QUESTION: 0.84,
            QueryIntent.TABLE_PREVIEW_QUERY: 0.88,
            QueryIntent.ANALYTICS_QUERY: 0.80,
            QueryIntent.UNSUPPORTED_QUERY: 0.98,
        }[selected_intent]

        signal_boost = min(len(matched_signals) * 0.035, 0.10)
        ambiguity_penalty = 0.07 if self._is_ambiguous(matched_intents) else 0.0
        short_query_penalty = 0.04 if len(normalized_question.split()) <= 2 else 0.0

        confidence = (
            base_confidence
            + signal_boost
            - ambiguity_penalty
            - short_query_penalty
        )

        return round(max(min(confidence, 0.99), 0.40), 2)

    def _build_reason(
        self,
        selected_intent: QueryIntent,
        matched_signals: list[str],
        matched_intents: list[QueryIntent],
    ) -> str:
        if selected_intent == QueryIntent.UNSUPPORTED_QUERY:
            return "Question requests an unsupported or unsafe operation."

        if matched_signals:
            matched_intent_values = ", ".join(
                intent.value for intent in matched_intents
            )
            return (
                f"Matched routing signals for {selected_intent.value}. "
                f"Matched intent groups: {matched_intent_values}."
            )

        return (
            "No strong specialized routing signal was detected. "
            "Defaulted to analytics workflow."
        )

    @staticmethod
    def _is_ambiguous(matched_intents: list[QueryIntent]) -> bool:
        competing_intents = {
            intent
            for intent in matched_intents
            if intent
            not in {
                QueryIntent.ANALYTICS_QUERY,
                QueryIntent.VISUALIZATION_QUERY,
            }
        }

        return len(competing_intents) > 1

    @staticmethod
    def _normalize_question(question: str | None) -> str:
        if question is None:
            return ""

        question = question.strip().lower()
        question = re.sub(r"\s+", " ", question)

        return question

    @staticmethod
    def _match_patterns(
        text: str,
        patterns: Iterable[IntentPattern],
    ) -> list[str]:
        matched_signals: list[str] = []

        for intent_pattern in patterns:
            if re.search(intent_pattern.pattern, text, flags=re.IGNORECASE):
                matched_signals.append(intent_pattern.signal)

        return matched_signals