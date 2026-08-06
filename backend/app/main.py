from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.models.project import Project  # noqa: F401
from app.models.asset import Asset  # noqa: F401
from app.models.document import Document  # noqa: F401
from app.models.conflict import Conflict  # noqa: F401
from app.models.pdf_extraction import (  # noqa: F401
    DocumentBlob, PdfPageText, PdfPoleEvidence, PdfProcessingJob, PdfRenderedPage,
)
from app.models.pole_entity import PoleEntity, PoleEntityAudit, PoleEntitySource, PoleRelationship  # noqa: F401


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="2.0.0-sprint0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "TelecomOS API", "version": "2.0.0-sprint0"}


@app.get("/health")
def health() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
