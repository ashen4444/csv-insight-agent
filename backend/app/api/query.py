from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.schema_context_builder import build_schema_context
from app.services.sql_validator import validate_sql
from app.services.query_executor import execute_query
from app.services.sql_generator import generate_sql_from_question

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
        raise HTTPException(status_code=404, detail="Dataset not found")

    if contains_unsafe_intent(request.question):
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsafe data modification requests are not supported. "
                "Only read-only analytical questions are allowed."
            ),
        )

    generated_sql = generate_sql_from_question(
        table_name=schema_context["table_name"],
        schema_profile=schema_context["schema_profile"],
        question=request.question,
    )

    try:
        validate_sql(generated_sql, schema_context)
        execution_result = execute_query(generated_sql)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "dataset_id": request.dataset_id,
        "question": request.question,
        **execution_result,
    }