import re

import duckdb
import pandas as pd

from backend.app.core.config import DUCKDB_PATH


class DuckDBService:
    def __init__(self, database_path=DUCKDB_PATH):
        self.database_path = database_path

    @staticmethod
    def sanitize_table_name(name: str) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower())
        sanitized = re.sub(r"_+", "_", sanitized).strip("_")

        if not sanitized:
            sanitized = "uploaded_data"

        if sanitized[0].isdigit():
            sanitized = f"table_{sanitized}"

        return sanitized

    def create_table_from_dataframe(
        self,
        dataframe: pd.DataFrame,
        table_name: str,
    ) -> str:
        sanitized_table_name = self.sanitize_table_name(table_name)

        with duckdb.connect(str(self.database_path)) as connection:
            connection.register("uploaded_dataframe", dataframe)
            connection.execute(
                f'CREATE OR REPLACE TABLE "{sanitized_table_name}" AS '
                "SELECT * FROM uploaded_dataframe"
            )
            connection.unregister("uploaded_dataframe")

        return sanitized_table_name