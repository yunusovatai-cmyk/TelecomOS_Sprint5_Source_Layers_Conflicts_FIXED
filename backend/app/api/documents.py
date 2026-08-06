import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app.core.config import settings
from app.db.deps import get_db
from app.models.document import Document
from app.models.pdf_extraction import DocumentBlob, PdfRenderedPage
from app.schemas.document import DocumentRead
from app.services.object_storage import get_object
from app.services.pdf_pole_extractor import render_pdf_page

router = APIRouter(prefix="/documents", tags=["documents"])

@router.get("", response_model=list[DocumentRead])
def list_documents(project_id: uuid.UUID | None = None, document_type: str | None = None, db: Session = Depends(get_db)) -> list[Document]:
    statement = select(Document).order_by(Document.created_at.desc())
    if project_id: statement = statement.where(Document.project_id == project_id)
    if document_type: statement = statement.where(Document.document_type == document_type)
    return list(db.scalars(statement))


@router.get("/{document_id}/page/{page_number}.png")
async def document_page_png(
    document_id: uuid.UUID, page_number: int, project_id: uuid.UUID = Query(...), db: Session = Depends(get_db),
) -> Response:
    document = db.scalar(select(Document).where(
        Document.id == document_id, Document.project_id == project_id, Document.document_type == "PDF",
    ))
    if document is None:
        raise HTTPException(status_code=404, detail="PDF document not found.")
    rendered = db.scalar(select(PdfRenderedPage).where(
        PdfRenderedPage.document_id == document.id, PdfRenderedPage.page_number == page_number,
    ))
    try:
        if rendered:
            png = await run_in_threadpool(get_object, rendered.bucket, rendered.object_key)
        else:
            if document.storage_bucket and document.storage_object_key:
                content = await run_in_threadpool(get_object, document.storage_bucket, document.storage_object_key)
            else:
                legacy = db.scalar(select(DocumentBlob).where(DocumentBlob.document_id == document.id))
                if legacy is None:
                    raise HTTPException(status_code=404, detail="Stored PDF content not found.")
                content = legacy.content
            png = await asyncio.wait_for(
                run_in_threadpool(render_pdf_page, content, page_number, max_pixels=settings.pdf_max_render_pixels),
                timeout=30,
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="PDF page rendering timed out.") from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Unable to render PDF page.") from exc
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
