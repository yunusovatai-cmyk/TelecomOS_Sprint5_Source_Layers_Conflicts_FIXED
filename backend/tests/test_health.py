from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["name"] == "TelecomOS API"


def test_lifespan_initializes_database_and_disposes_engine(monkeypatch):
    calls = []
    monkeypatch.setattr(main.Base.metadata, "create_all", lambda *, bind: calls.append(("startup", bind)))
    monkeypatch.setattr(main.engine, "dispose", lambda: calls.append(("shutdown", main.engine)))

    with TestClient(app) as lifecycle_client:
        response = lifecycle_client.get("/")
        assert response.status_code == 200
        assert calls == [("startup", main.engine)]

    assert calls == [("startup", main.engine), ("shutdown", main.engine)]


def test_documents_reject_invalid_project_uuid():
    response = client.get("/api/v1/documents", params={"project_id": "not-a-uuid"})
    assert response.status_code == 422


def test_assets_reject_invalid_project_uuid():
    response = client.get("/api/v1/assets", params={"project_id": "not-a-uuid"})
    assert response.status_code == 422


def test_package_import_rejects_invalid_project_uuid():
    response = client.post(
        "/api/v1/package-imports",
        data={"project_id": "not-a-uuid"},
        files={"files": ("sample.csv", b"name", "text/csv")},
    )
    assert response.status_code == 422


def test_review_rejects_invalid_project_uuid():
    response = client.get("/api/v1/review", params={"project_id": "not-a-uuid"})
    assert response.status_code == 422


def test_conflicts_reject_invalid_project_uuid():
    response = client.get("/api/v1/conflicts", params={"project_id": "not-a-uuid"})
    assert response.status_code == 422


def test_conflict_rebuild_rejects_invalid_project_uuid():
    response = client.post("/api/v1/conflicts/rebuild", params={"project_id": "not-a-uuid"})
    assert response.status_code == 422
