import io
import asyncio
import uuid
import zipfile

import pytest
from fastapi import UploadFile

from app.api import package_imports
from app.api.package_imports import UnsafePackageError, _extract_zip, import_project_package
from app.models.asset import Asset
from app.models.document import Document
from app.models.project import Project


def _zip(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content))


class FakeSession:
    def __init__(self):
        self.added = []

    def get(self, model, object_id):
        return None

    def scalar(self, statement):
        params = statement.compile().params
        digest = next((value for key, value in params.items() if key.startswith("sha256_")), None)
        if digest:
            return next(
                (item for item in self.added if isinstance(item, Document) and item.sha256 == digest),
                None,
            )
        return None

    def add(self, item):
        if getattr(item, "id", None) is None and isinstance(item, (Project, Document, Asset)):
            item.id = uuid.uuid4()
        self.added.append(item)

    def flush(self):
        pass

    def commit(self):
        pass


def test_extract_zip_recurses_without_writing_to_disk():
    nested = _zip({"maps/site.kml": b"<kml />", "docs/readme.pdf": b"pdf"})
    result = _extract_zip(_zip({"nested/package.zip": nested, "photos/pole.jpg": b"jpg"}))

    assert [item.filename for item in result] == [
        "nested/package.zip/maps/site.kml",
        "nested/package.zip/docs/readme.pdf",
        "photos/pole.jpg",
    ]


@pytest.mark.parametrize("name", ["../secret.txt", "/etc/passwd", "folder\\..\\secret.txt"])
def test_extract_zip_rejects_path_traversal(name):
    with pytest.raises(UnsafePackageError, match="Unsafe archive path"):
        _extract_zip(_zip({name: b"content"}))


def test_extract_zip_enforces_file_count(monkeypatch):
    monkeypatch.setattr(package_imports, "MAX_PACKAGE_FILES", 2)
    with pytest.raises(UnsafePackageError, match="more than 2 files"):
        _extract_zip(_zip({"a.csv": b"a", "b.csv": b"b", "c.csv": b"c"}))


def test_extract_zip_rejects_suspicious_compression_ratio():
    with pytest.raises(UnsafePackageError, match="compression ratio"):
        _extract_zip(_zip({"bomb.csv": b"0" * 100_000}))


def test_project_package_registers_files_parses_kml_and_skips_sha256_duplicate():
    kml = b'''<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>
    <name>Test</name><Placemark><name>Pole 1</name><Point><coordinates>-121.0,38.0</coordinates></Point></Placemark>
    </Document></kml>'''
    package = _zip({"maps/site.kml": kml, "docs/plan.pdf": b"pdf", "copies/plan.pdf": b"pdf"})
    db = FakeSession()

    response = asyncio.run(
        import_project_package(
            files=[_upload("project.zip", package)],
            project_id=None,
            project_name="Package Test",
            db=db,
        )
    )

    documents = [item for item in db.added if isinstance(item, Document)]
    assets = [item for item in db.added if isinstance(item, Asset)]
    assert response["report"] == {
        "found": 3,
        "registered": 2,
        "parsed": 1,
        "skipped": 1,
        "errors": [],
    }
    assert {document.document_type for document in documents} == {"KML", "PDF"}
    assert len(assets) == 1
    assert assets[0].source_document_id == next(
        document.id for document in documents if document.document_type == "KML"
    )


def test_single_file_upload_still_uses_existing_registration_path():
    db = FakeSession()
    response = asyncio.run(
        import_project_package(
            files=[_upload("survey.csv", b"name,latitude,longitude")],
            project_id=None,
            project_name="Single File Test",
            db=db,
        )
    )

    assert response["report"]["found"] == 1
    assert response["report"]["registered"] == 1
    document = next(item for item in db.added if isinstance(item, Document))
    assert document.filename == "survey.csv"
    assert document.document_type == "SPREADSHEET"
    assert document.processing_status == "REGISTERED"
