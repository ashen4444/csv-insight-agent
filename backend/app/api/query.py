from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.schema_context_builder import build_schema_context
from app.services.sql_validator import validate_sql
from app.services.query_executor import execute_query

router = APIRouter(prefix="/api/query", tags=["Query"])


class QueryRequest(BaseModel):
    dataset_id: str
    question: str


@router.post("")
def ask_dataset_question(request: QueryRequest):
    schema_context = build_schema_context(request.dataset_id)

    if schema_context is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Temporary hardcoded SQL for foundation testing
    generated_sql = f'SELECT * FROM "{schema_context["table_name"]}" LIMIT 5'

    validate_sql(generated_sql)

    results = execute_query(generated_sql)

    return {
        "dataset_id": request.dataset_id,
        "question": request.question,
        "sql": generated_sql,
        "results": results,
    }