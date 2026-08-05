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
  find "$temporary_dir" -depth -delete 2>/dev/null || true
  exit "$exit_code"
}
trap cleanup EXIT

python3 backend/tests/data/e2e/generate_pdf_entity_fixture.py "$temporary_dir/permit.pdf"

docker compose down -v --remove-orphans
docker compose up -d --build --wait --wait-timeout 180

curl --fail --silent --show-error -X POST "$api_base/package-imports" \
  -F 'project_name=PDF Entity E2E' \
  -F 'files=@backend/tests/data/e2e/pdf_entity_fixture.kml;type=application/vnd.google-earth.kml+xml' \
  > "$temporary_dir/kml.json"
project_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["project"]["id"])' "$temporary_dir/kml.json")"

curl --fail --silent --show-error -X POST "$api_base/pdf-pole-extractions/dry-run" \
  -F "project_id=$project_id" \
  -F "file=@$temporary_dir/permit.pdf;type=application/pdf" \
  > "$temporary_dir/dry-run.json"
document_id="$(python3 -c 'import json,sys; data=json.load(open(sys.argv[1])); assert data["assets_created"] == 0; assert data["summary"]["spans"] == 2; print(data["document"]["id"])' "$temporary_dir/dry-run.json")"

curl --fail --silent --show-error -X POST "$api_base/pdf-pole-extractions/$document_id/commit" \
  -H 'Content-Type: application/json' \
  -d '{"confirmed":true,"reason":"PDF Entity E2E commit","reviewer":"automation"}' \
  > "$temporary_dir/commit.json"
curl --fail --silent --show-error -X POST "$api_base/pdf-pole-extractions/$document_id/resolve" \
  -H 'Content-Type: application/json' -d '{"dry_run":false}' \
  > "$temporary_dir/resolve.json"

curl --fail --silent --show-error "$api_base/pole-entities?project_id=$project_id&limit=100" > "$temporary_dir/entities.json"
curl --fail --silent --show-error "$api_base/pole-relationships?project_id=$project_id&limit=100" > "$temporary_dir/relationships.json"
curl --fail --silent --show-error "$api_base/review/pdf-items?project_id=$project_id&limit=100" > "$temporary_dir/review.json"
python3 - "$temporary_dir/entities.json" "$temporary_dir/relationships.json" "$temporary_dir/review.json" <<'PY'
import json,sys
entities=json.load(open(sys.argv[1]))["items"]
relationships=json.load(open(sys.argv[2]))["items"]
review=json.load(open(sys.argv[3]))["items"]
statuses={item["canonical_pole_id"]:item["resolution_status"] for item in entities}
assert statuses["111111111"] == "RESOLVED"
assert statuses["222222222"] == "RESOLVED"
assert statuses["333333333"] == "AMBIGUOUS"
assert statuses["444444444"] == "RESOLVED"
assert statuses["555555555"] == "UNRESOLVED"
assert sorted(item["resolution_status"] for item in relationships) == ["PARTIAL", "RESOLVED"]
assert {item["type"] for item in review} >= {"UNMATCHED_PDF_POLE", "AMBIGUOUS_PDF_POLE", "PARTIAL_PDF_SPAN"}
PY

unmatched_entity_id="$(python3 -c 'import json,sys; print(next(x["id"] for x in json.load(open(sys.argv[1]))["items"] if x["canonical_pole_id"]=="555555555"))' "$temporary_dir/entities.json")"
curl --fail --silent --show-error "$api_base/assets?project_id=$project_id" > "$temporary_dir/assets.json"
manual_asset_id="$(python3 -c 'import json,sys; print(next(x["id"] for x in json.load(open(sys.argv[1])) if x["name"]=="Pole Manual Candidate"))' "$temporary_dir/assets.json")"
curl --fail --silent --show-error -X PATCH "$api_base/pole-entities/$unmatched_entity_id/manual-match" \
  -H 'Content-Type: application/json' \
  -d "{\"asset_id\":\"$manual_asset_id\",\"reason\":\"E2E field confirmation\",\"reviewer\":\"automation\"}" \
  > "$temporary_dir/manual.json"
python3 -c 'import json,sys; data=json.load(open(sys.argv[1])); assert data["resolution_status"]=="MANUAL"; assert data["longitude"] is not None' "$temporary_dir/manual.json"

curl --fail --silent --show-error "$api_base/assets/$manual_asset_id/pdf-evidence" > "$temporary_dir/asset-evidence.json"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["total"] > 0' "$temporary_dir/asset-evidence.json"
curl --fail --silent --show-error "http://127.0.0.1:3000/pdf-review/$document_id?page=1" | grep -q '<div id="root"></div>'

curl --fail --silent --show-error -X POST "$api_base/pdf-pole-extractions/$document_id/compare" > "$temporary_dir/conflicts.json"
python3 -c 'import json,sys; types={x["conflict_type"] for x in json.load(open(sys.argv[1]))["conflicts"]}; assert "PDF_SPAN_TOPOLOGY_MISMATCH" in types, types' "$temporary_dir/conflicts.json"

curl --fail --silent --show-error -X POST "$api_base/pdf-pole-extractions/$document_id/commit" \
  -H 'Content-Type: application/json' \
  -d '{"confirmed":true,"reason":"Idempotency check","reviewer":"automation"}' \
  > "$temporary_dir/commit-again.json"
python3 -c 'import json,sys; data=json.load(open(sys.argv[1])); assert data["relationships"]["created"]==0; assert data["relationships"]["reused"]==2; assert data["assets_created"]==0' "$temporary_dir/commit-again.json"

echo "PDF Entity E2E passed: project=$project_id document=$document_id manual_asset=$manual_asset_id"
