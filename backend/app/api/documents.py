from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.deps import get_db
from app.models.document import Document
from app.schemas.document import DocumentRead

router = APIRouter(prefix="/documents", tags=["documents"])

@router.get("", response_model=list[DocumentRead])
def list_documents(project_id: str | None = None, document_type: str | None = None, db: Session = Depends(get_db)) -> list[Document]:
    statement = select(Document).order_by(Document.created_at.desc())
    if project_id: statement = statement.where(Document.project_id == project_id)
    if document_type: statement = statement.where(Document.document_type == document_type)
    return list(db.scalars(statement))
