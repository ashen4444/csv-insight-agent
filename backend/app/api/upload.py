from pathlib import Path

from fastapi import APIRouter, File, UploadFile

from backend.app.services.csv_loader import (
    load_csv_to_dataframe,
    save_uploaded_csv,
)
from backend.app.services.duckdb_service import DuckDBService
from backend.app.services.schema_profiler import SchemaProfiler

router = APIRouter(prefix="/upload", tags=["CSV Upload"])


@router.post("/csv")
async def upload_csv(file: UploadFile = File(...)):
    saved_path = await save_uploaded_csv(file)

    dataframe = load_csv_to_dataframe(saved_path)

    duckdb_service = DuckDBService()

    table_name = duckdb_service.create_table_from_dataframe(
        dataframe=dataframe,
        table_name=Path(saved_path).stem,
    )

    schema_profile = SchemaProfiler.generate_profile(
        dataframe=dataframe,
        table_name=table_name,
        original_filename=file.filename or saved_path.name,
    )

    return {
        "message": "CSV uploaded and profiled successfully.",
        "saved_filename": saved_path.name,
        "table_name": table_name,
        "schema_profile": schema_profile,
    }