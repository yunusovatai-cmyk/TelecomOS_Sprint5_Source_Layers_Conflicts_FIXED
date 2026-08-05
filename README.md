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
