# TelecomOS — Sprint 5 Source Layers & Conflicts

Adds the first real cross-source comparison workflow.

## New functionality

- Preserve assets from multiple GIS documents in one project
- Link each asset to its source document
- Detect same-named route conflicts:
  - AERIAL_SPAN vs UG_SEGMENT
- Conflict list under the Engineering Map
- Show source document and revision for each variant
- Engineer can choose:
  - Aerial
  - UG
  - Needs Review
- Save decision and reason in PostgreSQL

## Start

```bash
cd ~/Downloads/TelecomOS_Sprint4_MultiSource_Registry
docker compose down

cd ~/Downloads/TelecomOS_Sprint5_Source_Layers_Conflicts
docker compose up --build --force-recreate
```

Open `http://127.0.0.1:3000`.

Import two GIS files into the same project where the same segment name is represented once as Aerial and once as UG. Open Engineering Map and click `Detect Conflicts`.

## Automated E2E smoke test

The smoke test uses only the small fixtures under `backend/tests/data/e2e`. It starts a clean Docker Compose stack, loads the demo project, imports a KMZ, verifies point and line assets, creates and resolves an `AERIAL_VS_UG` conflict, exercises Review Queue, and verifies asset status persistence.

Run it from the repository root:

```bash
./scripts/e2e_smoke.sh
```

The stack and its test volumes are removed automatically when the test finishes. Docker, Docker Compose, `curl`, `zip`, and Python 3 are required.

## CI

GitHub Actions runs on every push and pull request:

- Backend dependency installation, Python compile check, and pytest.
- Frontend installation with `npm ci`, TypeScript validation, and production build.
- Docker Compose build and startup with health checks, followed by the full E2E smoke test.

No repository secrets are required by the workflow. On a Docker smoke failure, service status and Compose logs are printed before volumes are removed.

## Background PDF processing

Large permit-plan PDFs can be stored privately in MinIO and processed by the Redis-backed worker without blocking the API or UI. See [docs/pdf-processing-jobs.md](docs/pdf-processing-jobs.md) for the architecture, API contract, migration procedure, queue diagnostics, retention guidance and rollback notes.

Run the reproducible background workflow with generated fixtures only:

```bash
./scripts/background_pdf_e2e.sh
```
