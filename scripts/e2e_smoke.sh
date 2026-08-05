#!/usr/bin/env bash
set -euo pipefail

repository_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_dir"

temporary_dir="$(mktemp -d)"
api_base="http://127.0.0.1:8000/api/v1"

cleanup() {
  exit_code=$?
  trap - EXIT
  if [[ $exit_code -ne 0 ]]; then
    docker compose ps || true
    docker compose logs --no-color || true
  fi
  docker compose down -v --remove-orphans || true
  rm -rf "$temporary_dir"
  exit "$exit_code"
}
trap cleanup EXIT

zip -j -q "$temporary_dir/mini_project.kmz" backend/tests/data/e2e/mini_project.kml
zip -j -q "$temporary_dir/conflict_package.zip" \
  backend/tests/data/e2e/conflict_aerial.kml \
  backend/tests/data/e2e/conflict_ug.kml

docker compose down -v --remove-orphans
docker compose up -d --build --wait --wait-timeout 180

curl --fail --silent --show-error "$api_base/projects" > "$temporary_dir/projects.json"
curl --fail --silent --show-error "http://127.0.0.1:3000/" > "$temporary_dir/frontend.html"
grep -q '<div id="root"></div>' "$temporary_dir/frontend.html"

curl --fail --silent --show-error -X POST "$api_base/demo/load" \
  > "$temporary_dir/demo.json"

curl --fail --silent --show-error -X POST "$api_base/imports/kmz" \
  -F "file=@$temporary_dir/mini_project.kmz;type=application/vnd.google-earth.kmz" \
  > "$temporary_dir/kmz_import.json"

project_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["project"]["id"])' "$temporary_dir/kmz_import.json")"

curl --fail --silent --show-error "$api_base/assets?project_id=$project_id" \
  > "$temporary_dir/assets.json"
python3 - "$temporary_dir/assets.json" <<'PY'
import json
import sys

assets = json.load(open(sys.argv[1]))
assert assets, "KMZ import created no assets"
assert any(item["geometry_type"] == "Point" for item in assets), "No Point asset created"
assert any(item["geometry_type"] == "LineString" for item in assets), "No LineString asset created"
PY

curl --fail --silent --show-error -X POST "$api_base/package-imports" \
  -F "project_id=$project_id" \
  -F "files=@$temporary_dir/conflict_package.zip;type=application/zip" \
  > "$temporary_dir/package_import.json"

curl --fail --silent --show-error -X POST "$api_base/conflicts/rebuild?project_id=$project_id" \
  > "$temporary_dir/conflicts.json"
conflict_id="$(python3 -c 'import json,sys; data=json.load(open(sys.argv[1])); matches=[x for x in data if x["conflict_type"]=="AERIAL_VS_UG"]; assert matches, data; print(matches[0]["id"])' "$temporary_dir/conflicts.json")"

curl --fail --silent --show-error "$api_base/review?project_id=$project_id" \
  > "$temporary_dir/review.json"
asset_id="$(python3 -c 'import json,sys; data=json.load(open(sys.argv[1])); assert data, "Review Queue is empty"; print(data[0]["id"])' "$temporary_dir/review.json")"

curl --fail --silent --show-error -X PATCH "$api_base/assets/$asset_id" \
  -H 'Content-Type: application/json' -d '{"status":"APPROVED"}' \
  > "$temporary_dir/asset_approved.json"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["status"] == "APPROVED"' "$temporary_dir/asset_approved.json"

curl --fail --silent --show-error -X PATCH "$api_base/assets/$asset_id" \
  -H 'Content-Type: application/json' -d '{"status":"REVIEW"}' \
  > "$temporary_dir/asset_review.json"
curl --fail --silent --show-error "$api_base/assets/$asset_id" \
  > "$temporary_dir/asset_persisted.json"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["status"] == "REVIEW"' "$temporary_dir/asset_persisted.json"

curl --fail --silent --show-error -X PATCH "$api_base/conflicts/$conflict_id" \
  -H 'Content-Type: application/json' \
  -d '{"decision":"UG","decision_reason":"Automated E2E smoke test"}' \
  > "$temporary_dir/conflict_resolved.json"
curl --fail --silent --show-error "$api_base/conflicts?project_id=$project_id" \
  > "$temporary_dir/conflicts_persisted.json"
python3 - "$temporary_dir/conflicts_persisted.json" "$conflict_id" <<'PY'
import json
import sys

conflicts = json.load(open(sys.argv[1]))
resolved = next(item for item in conflicts if item["id"] == sys.argv[2])
assert resolved["status"] == "RESOLVED"
assert resolved["decision"] == "UG"
assert resolved["decision_reason"] == "Automated E2E smoke test"
PY

echo "E2E smoke passed: project=$project_id asset=$asset_id conflict=$conflict_id"
