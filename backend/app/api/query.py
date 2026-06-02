from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.schema_context_builder import build_schema_context
from app.services.sql_validator import validate_sql
from app.services.query_executor import execute_query
from app.services.sql_generator import generate_sql_from_question
from app.services.query_audit_logger import write_query_audit_log
from app.services.result_analyzer import analyze_results
from app.services.visualization_intent_detector import detect_visualization_intent
from app.services.chart_selector import select_chart
from app.services.chart_payload_builder import build_chart_payload

router = APIRouter(prefix="/api/query", tags=["Query"])


UNSAFE_INTENT_KEYWORDS = {
    "delete",
    "remove",
    "drop",
    "truncate",
    "update",
    "insert",
    "modify",
    "alter",
    "clear",
    "erase",
}


class QueryRequest(BaseModel):
    dataset_id: str
    question: str


def contains_unsafe_intent(question: str) -> bool:
    question_lower = question.lower()

    return any(
        keyword in question_lower
        for keyword in UNSAFE_INTENT_KEYWORDS
    )


@router.post("")
def ask_dataset_question(request: QueryRequest):
    schema_context = build_schema_context(request.dataset_id)

    if schema_context is None:
        write_query_audit_log({
            "dataset_id": request.dataset_id,
            "question": request.question,
            "status": "dataset_not_found",
            "error_message": "Dataset not found",
        })

        raise HTTPException(status_code=404, detail="Dataset not found")

    if contains_unsafe_intent(request.question):
        error_message = (
            "Unsafe data modification requests are not supported. "
            "Only read-only analytical questions are allowed."
        )

        write_query_audit_log({
            "dataset_id": request.dataset_id,
            "question": request.question,
            "table_name": schema_context["table_name"],
            "status": "unsafe_intent_blocked",
            "error_message": error_message,
        })

        raise HTTPException(status_code=400, detail=error_message)

    generated_sql = generate_sql_from_question(
        table_name=schema_context["table_name"],
        schema_profile=schema_context["schema_profile"],
        question=request.question,
    )

    visualization_intent = detect_visualization_intent(request.question)

    try:
        validate_sql(generated_sql, schema_context)
        execution_result = execute_query(generated_sql)
        analysis = analyze_results(
            results=execution_result["results"],
            question=request.question,
            visualization_intent=visualization_intent,
        )

        chart_selection = select_chart(
            analysis=analysis,
            visualization_intent=visualization_intent,
        )

        chart_payload = build_chart_payload(
            results=execution_result["results"],
            analysis=analysis,
            chart_selection=chart_selection,
        )

    except ValueError as exc:
        write_query_audit_log({
            "dataset_id": request.dataset_id,
            "question": request.question,
            "table_name": schema_context["table_name"],
            "generated_sql": generated_sql,
            "status": "failed",
            "error_message": str(exc),
        })

        raise HTTPException(status_code=400, detail=str(exc))

    write_query_audit_log({
        "dataset_id": request.dataset_id,
        "question": request.question,
        "table_name": schema_context["table_name"],
        "generated_sql": generated_sql,
        "executed_sql": execution_result["sql"],
        "row_count": execution_result["row_count"],
        "execution_time_ms": execution_result["execution_time_ms"],
        "status": "success",
        "error_message": None,
    })

    return {
        "dataset_id": request.dataset_id,
        "question": request.question,
        **execution_result,
        "analysis": analysis,
        "visualization_intent": visualization_intent,
        "chart_selection": chart_selection,
        "chart_payload": chart_payload,
    }