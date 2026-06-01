from pathlib import Path

from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DUCKDB_DIR = DATA_DIR / "duckdb"
EXPORT_DIR = DATA_DIR / "exports"

DUCKDB_PATH = DUCKDB_DIR / "csvinsight.duckdb"

ALLOWED_FILE_EXTENSIONS = {".csv"}

MAX_UPLOAD_SIZE_MB = 25
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024


class Settings(BaseSettings):
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-4o-mini"

    class Config:
        env_file = BASE_DIR / ".env"


settings = Settings()


def ensure_data_directories() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    DUCKDB_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)