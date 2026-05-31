from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api.upload import router as upload_router
from backend.app.core.config import ensure_data_directories


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_data_directories()
    yield


app = FastAPI(
    title="CSVInsight Agent API",
    description="Privacy-aware CSV analytics backend.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "CSVInsight Agent API",
    }


app.include_router(upload_router, prefix="/api")