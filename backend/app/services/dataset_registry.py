import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import duckdb

from app.core.config import DUCKDB_PATH


class DatasetRegistry:
    def __init__(self, database_path=DUCKDB_PATH):
        self.database_path = database_path
        self._ensure_metadata_table()

    def _ensure_metadata_table(self) -> None:
        with duckdb.connect(str(self.database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_registry (
                    dataset_id VARCHAR PRIMARY KEY,
                    original_filename VARCHAR NOT NULL,
                    saved_filename VARCHAR NOT NULL,
                    table_name VARCHAR NOT NULL,
                    row_count INTEGER NOT NULL,
                    column_count INTEGER NOT NULL,
                    schema_profile JSON,
                    uploaded_at TIMESTAMP NOT NULL
                )
                """
            )

            existing_columns = connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'dataset_registry'
                """
            ).fetchall()

            existing_column_names = {column[0] for column in existing_columns}

            if "schema_profile" not in existing_column_names:
                connection.execute(
                    """
                    ALTER TABLE dataset_registry
                    ADD COLUMN schema_profile JSON
                    """
                )

    def register_dataset(
        self,
        original_filename: str,
        saved_filename: str,
        table_name: str,
        schema_profile: dict[str, Any],
    ) -> dict[str, Any]:
        dataset_id = uuid4().hex[:12]
        uploaded_at = datetime.now(timezone.utc).replace(tzinfo=None)

        row_count = schema_profile["dataset"]["row_count"]
        column_count = schema_profile["dataset"]["column_count"]

        with duckdb.connect(str(self.database_path)) as connection:
            connection.execute(
                """
                INSERT INTO dataset_registry (
                    dataset_id,
                    original_filename,
                    saved_filename,
                    table_name,
                    row_count,
                    column_count,
                    schema_profile,
                    uploaded_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    dataset_id,
                    original_filename,
                    saved_filename,
                    table_name,
                    row_count,
                    column_count,
                    json.dumps(schema_profile),
                    uploaded_at,
                ],
            )

        return {
            "dataset_id": dataset_id,
            "original_filename": original_filename,
            "saved_filename": saved_filename,
            "table_name": table_name,
            "row_count": row_count,
            "column_count": column_count,
            "schema_profile": schema_profile,
            "uploaded_at": uploaded_at.isoformat(),
        }

    def list_datasets(self) -> list[dict[str, Any]]:
        with duckdb.connect(str(self.database_path)) as connection:
            rows = connection.execute(
                """
                SELECT
                    dataset_id,
                    original_filename,
                    saved_filename,
                    table_name,
                    row_count,
                    column_count,
                    schema_profile,
                    uploaded_at
                FROM dataset_registry
                ORDER BY uploaded_at DESC
                """
            ).fetchall()

        return [
            {
                "dataset_id": row[0],
                "original_filename": row[1],
                "saved_filename": row[2],
                "table_name": row[3],
                "row_count": row[4],
                "column_count": row[5],
                "schema_profile": json.loads(row[6]) if row[6] else None,
                "uploaded_at": row[7].isoformat() if row[7] else None,
            }
            for row in rows
        ]

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with duckdb.connect(str(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT
                    dataset_id,
                    original_filename,
                    saved_filename,
                    table_name,
                    row_count,
                    column_count,
                    schema_profile,
                    uploaded_at
                FROM dataset_registry
                WHERE dataset_id = ?
                """,
                [dataset_id],
            ).fetchone()

        if row is None:
            return None

        return {
            "dataset_id": row[0],
            "original_filename": row[1],
            "saved_filename": row[2],
            "table_name": row[3],
            "row_count": row[4],
            "column_count": row[5],
            "schema_profile": json.loads(row[6]) if row[6] else None,
            "uploaded_at": row[7].isoformat() if row[7] else None,
        }


def list_datasets() -> list[dict[str, Any]]:
    registry = DatasetRegistry()
    return registry.list_datasets()


def get_dataset_by_id(dataset_id: str) -> dict[str, Any] | None:
    registry = DatasetRegistry()
    return registry.get_dataset(dataset_id)