from __future__ import annotations

from dataclasses import dataclass

from app.agents.intent_router.models import (
    IntentRouterResult,
    RouterDecisionSource,
    RoutingCapability,
)


@dataclass(frozen=True)
class DependencyCheckResult:
    can_proceed: bool
    blocking_reason: str | None = None
    user_message: str | None = None


class RoutingDependencyPolicy:
    """
    Validates whether the selected workflow can actually run.

    Important production decision:
    If the workflow needs LLM-based SQL generation and the model/API is
    unavailable, do not ask fake clarification questions. Stop with a clear
    model-unavailable response.
    """

    LLM_REQUIRED_CAPABILITIES = {
        RoutingCapability.SQL_GENERATION,
    }

    MODEL_UNAVAILABLE_MESSAGE = (
        "The AI model required for SQL generation is currently unavailable. "
        "Please check your API key, model configuration, or provider connection "
        "and try again."
    )

    def evaluate(
        self,
        result: IntentRouterResult,
        model_available: bool,
    ) -> DependencyCheckResult:
        if not result.is_routable:
            return DependencyCheckResult(can_proceed=False)

        if result.primary_intent.value == "unsupported_query":
            return DependencyCheckResult(can_proceed=True)

        requires_llm = any(
            capability in self.LLM_REQUIRED_CAPABILITIES
            for capability in result.required_capabilities
        )

        if requires_llm and not model_available:
            return DependencyCheckResult(
                can_proceed=False,
                blocking_reason="llm_required_but_model_unavailable",
                user_message=self.MODEL_UNAVAILABLE_MESSAGE,
            )

        return DependencyCheckResult(can_proceed=True)

    def apply(
        self,
        result: IntentRouterResult,
        model_available: bool,
    ) -> IntentRouterResult:
        dependency_check = self.evaluate(
            result=result,
            model_available=model_available,
        )

        if dependency_check.can_proceed:
            return result

        return IntentRouterResult(
            primary_intent=result.primary_intent,
            required_capabilities=[
                RoutingCapability.MODEL_UNAVAILABLE_RESPONSE,
                RoutingCapability.ANSWER_FORMATTING,
            ],
            confidence=result.confidence,
            reason=dependency_check.user_message or result.reason,
            source=RouterDecisionSource.DEPENDENCY_POLICY,
            matched_signals=result.matched_signals,
            normalized_question=result.normalized_question,
            llm_used=result.llm_used,
            needs_clarification=False,
            clarification_question=None,
            is_routable=False,
            blocking_reason=dependency_check.blocking_reason,
            unsupported_reason=result.unsupported_reason,
            metadata={
                **result.metadata,
                "model_available": model_available,
                "original_required_capabilities": [
                    capability.value for capability in result.required_capabilities
                ],
                "dependency_policy_applied": True,
            },
        )