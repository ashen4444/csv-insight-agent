import uuid
from pathlib import Path

import pandas as pd
from fastapi import HTTPException, UploadFile, status

from app.core.config import (
    ALLOWED_FILE_EXTENSIONS,
    MAX_UPLOAD_SIZE_BYTES,
    UPLOAD_DIR,
)


def validate_csv_file(filename: str) -> None:
    file_extension = Path(filename).suffix.lower()

    if file_extension not in ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV files are supported.",
        )


async def save_uploaded_csv(file: UploadFile) -> Path:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must have a filename.",
        )

    validate_csv_file(file.filename)

    original_name = Path(file.filename).stem
    safe_name = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in original_name
    )

    unique_id = uuid.uuid4().hex[:12]
    saved_filename = f"{safe_name}_{unique_id}.csv"
    saved_path = UPLOAD_DIR / saved_filename

    total_size = 0

    try:
        with saved_path.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)

                if total_size > MAX_UPLOAD_SIZE_BYTES:
                    saved_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Uploaded CSV file is too large.",
                    )

                buffer.write(chunk)

        return saved_path

    except HTTPException:
        raise

    except Exception as exc:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save uploaded CSV: {str(exc)}",
        ) from exc


def load_csv_to_dataframe(csv_path: Path) -> pd.DataFrame:
    try:
        dataframe = pd.read_csv(csv_path)

        if dataframe.empty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded CSV is empty.",
            )

        return dataframe

    except pd.errors.EmptyDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded CSV contains no readable data.",
        ) from exc

    except pd.errors.ParserError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded CSV could not be parsed.",
        ) from exc