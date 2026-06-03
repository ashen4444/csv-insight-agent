from app.agents.intent_router_agent import (
    IntentRouterAgent,
    QueryIntent,
    RoutingCapability,
)


def build_router() -> IntentRouterAgent:
    return IntentRouterAgent(
        enable_llm_fallback=False,
        model_available_override=True,
    )


def test_routes_analytics_query() -> None:
    router = build_router()

    result = router.classify("Average salary by country")

    assert result.primary_intent == QueryIntent.ANALYTICS_QUERY
    assert RoutingCapability.SQL_GENERATION in result.required_capabilities
    assert RoutingCapability.SQL_VALIDATION in result.required_capabilities
    assert RoutingCapability.QUERY_EXECUTION in result.required_capabilities
    assert RoutingCapability.RESULT_ANALYSIS in result.required_capabilities
    assert result.is_routable is True


def test_routes_visualization_query_with_analytics_capabilities() -> None:
    router = build_router()

    result = router.classify("Show a bar chart of average salary by country")

    assert result.primary_intent == QueryIntent.VISUALIZATION_QUERY
    assert RoutingCapability.SQL_GENERATION in result.required_capabilities
    assert RoutingCapability.SQL_VALIDATION in result.required_capabilities
    assert RoutingCapability.QUERY_EXECUTION in result.required_capabilities
    assert RoutingCapability.RESULT_ANALYSIS in result.required_capabilities
    assert RoutingCapability.CHART_SELECTION in result.required_capabilities
    assert RoutingCapability.CHART_PAYLOAD_GENERATION in result.required_capabilities
    assert RoutingCapability.CHART_VALIDATION in result.required_capabilities


def test_routes_table_preview_query_without_llm_sql_generation() -> None:
    router = build_router()

    result = router.classify("Show first 10 rows")

    assert result.primary_intent == QueryIntent.TABLE_PREVIEW_QUERY
    assert RoutingCapability.SQL_GENERATION not in result.required_capabilities
    assert RoutingCapability.SQL_VALIDATION in result.required_capabilities
    assert RoutingCapability.QUERY_EXECUTION in result.required_capabilities


def test_routes_schema_question() -> None:
    router = build_router()

    result = router.classify("What columns are available?")

    assert result.primary_intent == QueryIntent.SCHEMA_QUESTION
    assert RoutingCapability.SCHEMA_PROFILING in result.required_capabilities


def test_routes_data_quality_query() -> None:
    router = build_router()

    result = router.classify("Are there missing values?")

    assert result.primary_intent == QueryIntent.DATA_QUALITY_QUERY
    assert RoutingCapability.DATA_QUALITY_ANALYSIS in result.required_capabilities


def test_routes_data_quality_visualization_query() -> None:
    router = build_router()

    result = router.classify("Show a chart of missing values by column")

    assert result.primary_intent == QueryIntent.VISUALIZATION_QUERY
    assert RoutingCapability.DATA_QUALITY_ANALYSIS in result.required_capabilities
    assert RoutingCapability.SQL_GENERATION not in result.required_capabilities
    assert RoutingCapability.CHART_SELECTION in result.required_capabilities


def test_routes_unsupported_non_csv_task() -> None:
    router = build_router()

    result = router.classify("Tell me a joke")

    assert result.primary_intent == QueryIntent.UNSUPPORTED_QUERY
    assert result.unsupported_reason == "non_csv_task"
    assert RoutingCapability.UNSUPPORTED_RESPONSE in result.required_capabilities


def test_routes_unsupported_destructive_operation() -> None:
    router = build_router()

    result = router.classify("Delete this dataset")

    assert result.primary_intent == QueryIntent.UNSUPPORTED_QUERY
    assert result.unsupported_reason == "destructive_operation"


def test_blocks_llm_dependent_workflow_when_model_unavailable() -> None:
    router = IntentRouterAgent(
        enable_llm_fallback=False,
        model_available_override=False,
    )

    result = router.classify("Average salary by country")

    assert result.is_routable is False
    assert result.blocking_reason == "llm_required_but_model_unavailable"
    assert RoutingCapability.MODEL_UNAVAILABLE_RESPONSE in result.required_capabilities


def test_allows_table_preview_when_model_unavailable() -> None:
    router = IntentRouterAgent(
        enable_llm_fallback=False,
        model_available_override=False,
    )

    result = router.classify("Show first 5 rows")

    assert result.is_routable is True
    assert result.primary_intent == QueryIntent.TABLE_PREVIEW_QUERY
    assert RoutingCapability.SQL_GENERATION not in result.required_capabilities


def test_result_can_be_serialized_to_dict() -> None:
    router = build_router()

    result = router.classify("Average salary by country")
    payload = result.to_dict()

    assert payload["primary_intent"] == "analytics_query"
    assert "required_capabilities" in payload
    assert "confidence" in payload
    assert "metadata" in payload