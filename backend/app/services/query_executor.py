import duckdb

from app.core.config import DUCKDB_PATH

def execute_query(sql: str) -> list[dict]:
    with duckdb.connect(str(DUCKDB_PATH)) as conn:
        result_df = conn.execute(sql).fetchdf()

    return result_df.to_dict(orient="records")