#!/usr/bin/env bash
set -euo pipefail

repository_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_dir"
temporary_dir="$(mktemp -d)"
api_base="http://127.0.0.1:8000/api/v1"
cleanup() {
  exit_code=$?
  trap - EXIT
  if [[ $exit_code -ne 0 ]]; then docker compose ps || true; docker compose logs --no-color || true; fi
  docker compose down -v --remove-orphans || true
  find "$temporary_dir" -depth -delete 2>/dev/null || true
  exit "$exit_code"
}
trap cleanup EXIT

python3 backend/tests/data/e2e/generate_pdf_entity_fixture.py "$temporary_dir/permit.pdf"
docker compose down -v --remove-orphans
docker compose up -d --build --wait --wait-timeout 180
curl -fsS -X POST "$api_base/package-imports" -F 'project_name=Background PDF E2E' \
  -F 'files=@backend/tests/data/e2e/pdf_entity_fixture.kml;type=application/vnd.google-earth.kml+xml' > "$temporary_dir/project.json"
project_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["project"]["id"])' "$temporary_dir/project.json")"
curl -fsS -X POST "$api_base/pdf-jobs" -F "project_id=$project_id" \
  -F "file=@$temporary_dir/permit.pdf;type=application/pdf" > "$temporary_dir/job.json"
job_id="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["status"] in {"QUEUED","RUNNING"}; print(d["id"])' "$temporary_dir/job.json")"
document_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["document_id"])' "$temporary_dir/job.json")"
for _ in $(seq 1 120); do
  curl -fsS "$api_base/pdf-jobs/$job_id?project_id=$project_id" > "$temporary_dir/status.json"
  job_status="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$temporary_dir/status.json")"
  [[ "$job_status" == "SUCCEEDED" ]] && break
  [[ "$job_status" == "FAILED" || "$job_status" == "CANCELLED" ]] && { cat "$temporary_dir/status.json"; exit 1; }
  sleep 1
done
[[ "$job_status" == "SUCCEEDED" ]]
curl -fsS "$api_base/documents/$document_id/page/1.png?project_id=$project_id" -o "$temporary_dir/page.png"
python3 -c 'import sys; assert open(sys.argv[1],"rb").read(8)==b"\x89PNG\r\n\x1a\n"' "$temporary_dir/page.png"
curl -fsS "$api_base/pole-entities?project_id=$project_id" > "$temporary_dir/entities.json"
curl -fsS "$api_base/pole-relationships?project_id=$project_id" > "$temporary_dir/relationships.json"
python3 - "$temporary_dir/entities.json" "$temporary_dir/relationships.json" <<'PY'
import json,sys
assert json.load(open(sys.argv[1]))["total"] >= 5
assert json.load(open(sys.argv[2]))["total"] == 2
PY
curl -fsS -X POST "$api_base/pdf-jobs" -F "project_id=$project_id" \
  -F "file=@$temporary_dir/permit.pdf;type=application/pdf" > "$temporary_dir/duplicate.json"
python3 - "$temporary_dir/duplicate.json" "$job_id" <<'PY'
import json,sys
d=json.load(open(sys.argv[1])); assert d["id"]==sys.argv[2]; assert d["duplicate_document"] and d["reused_job"]
PY
echo "Background PDF E2E passed: project=$project_id document=$document_id job=$job_id"
