from pathlib import Path

from app.db.base import Base
from app.db.session import engine
from app.models.asset import Asset  # noqa: F401
from app.models.conflict import Conflict  # noqa: F401
from app.models.document import Document  # noqa: F401
from app.models.pdf_extraction import (  # noqa: F401
    DocumentBlob, PdfPageText, PdfPoleEvidence, PdfProcessingJob, PdfRenderedPage,
)
from app.models.pole_entity import PoleEntity, PoleEntityAudit, PoleEntitySource, PoleRelationship  # noqa: F401
from app.models.project import Project  # noqa: F401


def main() -> None:
    Base.metadata.create_all(bind=engine)
    migration_dir = Path("/migrations")
    if not migration_dir.exists():
        return
    with engine.begin() as connection:
        for path in sorted(migration_dir.glob("*.sql")):
            connection.exec_driver_sql(path.read_text())


if __name__ == "__main__":
    main()
