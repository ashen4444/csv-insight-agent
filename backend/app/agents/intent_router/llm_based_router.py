from __future__ import annotations

import json
import os
import re
from typing import Any

from app.agents.intent_router.models import (
    IntentRouterResult,
    QueryIntent,
    RouterDecisionSource,
    build_required_capabilities,
)


class LLMIntentRouter:
    """
    Semantic intent router.

    Used only when deterministic routing is uncertain or ambiguous.

    The LLM does not execute tools and does not control the workflow directly.
    It returns a structured routing recommendation.
    """

    SYSTEM_PROMPT = """
You are an intent classification component inside an enterprise CSV analytics system.

Classify the user's question into exactly one primary_intent.

Allowed primary_intent values:
- analytics_query
- visualization_query
- table_preview_query
- data_quality_query
- schema_question
- unsupported_query

Allowed unsupported_reason values when primary_intent is unsupported_query:
- destructive_operation
- external_web_request
- external_communication_request
- file_generation_request
- non_csv_task

Important routing rules:
1. visualization_query means the final user output should include a chart.
2. visualization_query does NOT bypass analytics.
3. For normal chart requests over dataset values, the workflow still needs:
   sql_generation, sql_validation, query_execution, result_analysis, and chart generation.
4. schema_question is for dataset metadata, columns, datatypes, row counts, column counts, and dataset structure.
5. data_quality_query is for missing values, duplicates, outliers, invalid values, inconsistent values, and cleanliness checks.
6. unsupported_query is for destructive operations, unrelated tasks, external web browsing, email/message sending, file generation, or requests outside CSV analytics.
7. If the user request is unrelated to CSV analysis, classify it as unsupported_query with unsupported_reason="non_csv_task".

Return ONLY valid JSON with this exact shape:
{
  "primary_intent": "analytics_query",
  "supporting_intents": [],
  "confidence": 0.0,
  "reason": "short reason",
  "needs_clarification": false,
  "clarification_question": null,
  "unsupported_reason": null
}

Examples:

User: "Show a chart of average salary by country"
JSON:
{
  "primary_intent": "visualization_query",
  "supporting_intents": ["analytics_query"],
  "confidence": 0.94,
  "reason": "User wants a chart based on an aggregate analytics query.",
  "needs_clarification": false,
  "clarification_question": null,
  "unsupported_reason": null
}

User: "Average salary by country"
JSON:
{
  "primary_intent": "analytics_query",
  "supporting_intents": [],
  "confidence": 0.92,
  "reason": "User asks for an aggregate grouped analytics result.",
  "needs_clarification": false,
  "clarification_question": null,
  "unsupported_reason": null
}

User: "What columns are available?"
JSON:
{
  "primary_intent": "schema_question",
  "supporting_intents": [],
  "confidence": 0.91,
  "reason": "User asks about dataset structure.",
  "needs_clarification": false,
  "clarification_question": null,
  "unsupported_reason": null
}

User: "Are there missing values?"
JSON:
{
  "primary_intent": "data_quality_query",
  "supporting_intents": [],
  "confidence": 0.93,
  "reason": "User asks about missing values in the dataset.",
  "needs_clarification": false,
  "clarification_question": null,
  "unsupported_reason": null
}

User: "Show a chart of missing values by column"
JSON:
{
  "primary_intent": "visualization_query",
  "supporting_intents": ["data_quality_query"],
  "confidence": 0.93,
  "reason": "User wants a visualization based on data quality analysis.",
  "needs_clarification": false,
  "clarification_question": null,
  "unsupported_reason": null
}

User: "Tell me a joke"
JSON:
{
  "primary_intent": "unsupported_query",
  "supporting_intents": [],
  "confidence": 0.96,
  "reason": "The request is unrelated to CSV analytics.",
  "needs_clarification": false,
  "clarification_question": null,
  "unsupported_reason": "non_csv_task"
}
""".strip()

    def __init__(
        self,
        llm: Any | None = None,
        model_name: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self.last_error: str | None = None
        self.llm = llm or self._build_default_llm(
            model_name=model_name,
            temperature=temperature,
        )

    @property
    def is_available(self) -> bool:
        return self.llm is not None

    def classify(
        self,
        question: str,
        normalized_question: str,
        rule_based_result: IntentRouterResult | None = None,
    ) -> IntentRouterResult | None:
        self.last_error = None

        if self.llm is None:
            self.last_error = "LLM router is not configured."
            return None

        prompt = self._build_user_prompt(
            question=question,
            normalized_question=normalized_question,
            rule_based_result=rule_based_result,
        )

        try:
            response = self.llm.invoke(prompt)
            content = self._extract_content(response)
            payload = self._parse_json(content)

            return self._payload_to_result(
                payload=payload,
                normalized_question=normalized_question,
            )
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def _build_user_prompt(
        self,
        question: str,
        normalized_question: str,
        rule_based_result: IntentRouterResult | None,
    ) -> list[tuple[str, str]]:
        rule_summary = "No rule-based result provided."

        if rule_based_result is not None:
            rule_summary = json.dumps(
                {
                    "primary_intent": rule_based_result.primary_intent.value,
                    "confidence": rule_based_result.confidence,
                    "matched_signals": rule_based_result.matched_signals,
                    "required_capabilities": [
                        capability.value
                        for capability in rule_based_result.required_capabilities
                    ],
                    "unsupported_reason": rule_based_result.unsupported_reason,
                    "metadata": rule_based_result.metadata,
                },
                indent=2,
            )

        user_prompt = f"""
Classify this CSV analytics user question.

Original question:
{question}

Normalized question:
{normalized_question}

Rule-based router result:
{rule_summary}

Return only valid JSON.
""".strip()

        return [
            ("system", self.SYSTEM_PROMPT),
            ("human", user_prompt),
        ]

    def _payload_to_result(
        self,
        payload: dict[str, Any],
        normalized_question: str,
    ) -> IntentRouterResult:
        primary_intent = self._parse_intent(
            payload.get("primary_intent"),
            fallback=QueryIntent.ANALYTICS_QUERY,
        )

        supporting_intents = [
            self._parse_intent(intent, fallback=None)
            for intent in payload.get("supporting_intents", [])
        ]
        supporting_intents = [
            intent
            for intent in supporting_intents
            if intent is not None and intent != primary_intent
        ]

        confidence = self._parse_confidence(payload.get("confidence"))

        reason = str(
            payload.get("reason") or "LLM generated routing decision."
        ).strip()

        needs_clarification = bool(payload.get("needs_clarification", False))
        clarification_question = payload.get("clarification_question")

        if clarification_question is not None:
            clarification_question = str(clarification_question).strip() or None

        unsupported_reason = payload.get("unsupported_reason")

        if unsupported_reason is not None:
            unsupported_reason = str(unsupported_reason).strip() or None

        return IntentRouterResult(
            primary_intent=primary_intent,
            required_capabilities=build_required_capabilities(
                primary_intent=primary_intent,
                supporting_intents=supporting_intents,
            ),
            confidence=confidence,
            reason=reason,
            source=RouterDecisionSource.LLM,
            matched_signals=[],
            normalized_question=normalized_question,
            llm_used=True,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            unsupported_reason=unsupported_reason,
            metadata={
                "supporting_intents": [
                    intent.value for intent in supporting_intents
                ],
                "raw_llm_payload": payload,
            },
        )

    @staticmethod
    def _build_default_llm(
        model_name: str | None,
        temperature: float,
    ) -> Any | None:
        if not os.getenv("OPENAI_API_KEY"):
            return None

        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            return None

        return ChatOpenAI(
            model=model_name or os.getenv(
                "OPENAI_INTENT_ROUTER_MODEL",
                "gpt-4o-mini",
            ),
            temperature=temperature,
        )

    @staticmethod
    def _extract_content(response: Any) -> str:
        if isinstance(response, str):
            return response

        content = getattr(response, "content", None)

        if isinstance(content, str):
            return content

        return str(response)

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        content = content.strip()

        fenced_match = re.search(
            r"```(?:json)?\s*(.*?)```",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )

        if fenced_match:
            content = fenced_match.group(1).strip()

        return json.loads(content)

    @staticmethod
    def _parse_intent(
        value: Any,
        fallback: QueryIntent | None,
    ) -> QueryIntent | None:
        try:
            return QueryIntent(str(value))
        except ValueError:
            return fallback

    @staticmethod
    def _parse_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except TypeError:
            return 0.70
        except ValueError:
            return 0.70

        return round(max(min(confidence, 0.99), 0.0), 2)