from __future__ import annotations

from dataclasses import dataclass

from app.agents.intent_router.models import IntentRouterResult, QueryIntent


@dataclass(frozen=True)
class ConfidencePolicy:
    """
    Central confidence policy for hybrid routing.

    This prevents confidence thresholds from being scattered across router code.
    """

    llm_fallback_threshold: float = 0.78
    llm_acceptance_threshold: float = 0.70

    def should_try_llm(
        self,
        rule_based_result: IntentRouterResult,
        enable_llm_fallback: bool,
    ) -> bool:
        if not enable_llm_fallback:
            return False

        if rule_based_result.primary_intent == QueryIntent.UNSUPPORTED_QUERY:
            return False

        if rule_based_result.confidence < self.llm_fallback_threshold:
            return True

        if rule_based_result.metadata.get("ambiguous") is True:
            return True

        if not rule_based_result.matched_signals:
            return True

        return False

    def should_accept_llm_result(
        self,
        rule_based_result: IntentRouterResult,
        llm_result: IntentRouterResult,
    ) -> bool:
        if llm_result.confidence < self.llm_acceptance_threshold:
            return False

        if llm_result.needs_clarification:
            return True

        return llm_result.confidence >= rule_based_result.confidence - 0.05