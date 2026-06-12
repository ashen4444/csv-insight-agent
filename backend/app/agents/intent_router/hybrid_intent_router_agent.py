from __future__ import annotations

from app.core.config import settings

from app.agents.intent_router.confidence_policy import ConfidencePolicy
from app.agents.intent_router.dependency_policy import RoutingDependencyPolicy
from app.agents.intent_router.llm_based_router import LLMIntentRouter
from app.agents.intent_router.models import (
    IntentRouterResult,
    QueryIntent,
    RouterDecisionSource,
)
from app.agents.intent_router.rule_based_router import RuleBasedIntentRouter


class IntentRouterAgent:
    """
    Final public Intent Router Agent.

    This is the only class the workflow should call.

    Internally it combines:
    - deterministic rule-based routing
    - optional LLM semantic fallback
    - confidence-based decision merging
    - model/API dependency policy

    LangGraph should later orchestrate this agent as a workflow node.
    LangGraph should not be used inside this class.
    """

    def __init__(
        self,
        rule_router: RuleBasedIntentRouter | None = None,
        llm_router: LLMIntentRouter | None = None,
        confidence_policy: ConfidencePolicy | None = None,
        dependency_policy: RoutingDependencyPolicy | None = None,
        enable_llm_fallback: bool = True,
        model_available_override: bool | None = None,
    ) -> None:
        self.rule_router = rule_router or RuleBasedIntentRouter()
        self.llm_router = llm_router or LLMIntentRouter()
        self.confidence_policy = confidence_policy or ConfidencePolicy()
        self.dependency_policy = dependency_policy or RoutingDependencyPolicy()
        self.enable_llm_fallback = enable_llm_fallback
        self.model_available_override = model_available_override

    def classify(self, question: str) -> IntentRouterResult:
        rule_result = self.rule_router.classify(question)

        if rule_result.primary_intent == QueryIntent.UNSUPPORTED_QUERY:
            return rule_result

        final_result = rule_result

        if self.confidence_policy.should_try_llm(
            rule_based_result=rule_result,
            enable_llm_fallback=self.enable_llm_fallback,
        ):
            llm_result = self.llm_router.classify(
                question=question,
                normalized_question=rule_result.normalized_question,
                rule_based_result=rule_result,
            )

            if llm_result is not None:
                final_result = self._merge_results(
                    rule_result=rule_result,
                    llm_result=llm_result,
                )
            else:
                final_result = self._attach_llm_failure_metadata(rule_result)

        return self.dependency_policy.apply(
            result=final_result,
            model_available=self._is_model_available(),
        )

    def _merge_results(
        self,
        rule_result: IntentRouterResult,
        llm_result: IntentRouterResult,
    ) -> IntentRouterResult:
        if not self.confidence_policy.should_accept_llm_result(
            rule_based_result=rule_result,
            llm_result=llm_result,
        ):
            return IntentRouterResult(
                primary_intent=rule_result.primary_intent,
                required_capabilities=rule_result.required_capabilities,
                confidence=rule_result.confidence,
                reason=rule_result.reason,
                source=RouterDecisionSource.HYBRID,
                matched_signals=rule_result.matched_signals,
                normalized_question=rule_result.normalized_question,
                llm_used=True,
                needs_clarification=rule_result.needs_clarification,
                clarification_question=rule_result.clarification_question,
                is_routable=rule_result.is_routable,
                blocking_reason=rule_result.blocking_reason,
                unsupported_reason=rule_result.unsupported_reason,
                metadata={
                    **rule_result.metadata,
                    "rule_based_result": rule_result.to_dict(),
                    "llm_result": llm_result.to_dict(),
                    "decision": "kept_rule_based_route",
                },
            )

        return IntentRouterResult(
            primary_intent=llm_result.primary_intent,
            required_capabilities=llm_result.required_capabilities,
            confidence=llm_result.confidence,
            reason=llm_result.reason,
            source=RouterDecisionSource.HYBRID,
            matched_signals=rule_result.matched_signals,
            normalized_question=rule_result.normalized_question,
            llm_used=True,
            needs_clarification=llm_result.needs_clarification,
            clarification_question=llm_result.clarification_question,
            is_routable=llm_result.is_routable,
            blocking_reason=llm_result.blocking_reason,
            unsupported_reason=llm_result.unsupported_reason,
            metadata={
                **llm_result.metadata,
                "rule_based_result": rule_result.to_dict(),
                "llm_result": llm_result.to_dict(),
                "decision": "accepted_llm_route",
            },
        )

    def _attach_llm_failure_metadata(
        self,
        rule_result: IntentRouterResult,
    ) -> IntentRouterResult:
        return IntentRouterResult(
            primary_intent=rule_result.primary_intent,
            required_capabilities=rule_result.required_capabilities,
            confidence=rule_result.confidence,
            reason=rule_result.reason,
            source=RouterDecisionSource.HYBRID,
            matched_signals=rule_result.matched_signals,
            normalized_question=rule_result.normalized_question,
            llm_used=False,
            needs_clarification=rule_result.needs_clarification,
            clarification_question=rule_result.clarification_question,
            is_routable=rule_result.is_routable,
            blocking_reason=rule_result.blocking_reason,
            unsupported_reason=rule_result.unsupported_reason,
            metadata={
                **rule_result.metadata,
                "llm_fallback_attempted": True,
                "llm_fallback_failed": True,
                "llm_error": self.llm_router.last_error,
            },
        )

    def _is_model_available(self) -> bool:
        if self.model_available_override is not None:
            return self.model_available_override

        return bool(
            settings.OPENAI_API_KEY
            and settings.OPENAI_MODEL
        )