import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api, apiBaseUrl } from "./services/api";

type Evidence = {
  id: string;
  type: "POLE_ID" | "SPAN" | "ANCHOR";
  page_number: number;
  pole_id: string | null;
  external_eid: string | null;
  from_pole_id: string | null;
  to_pole_id: string | null;
  span_length_ft: number | null;
  raw_text: string;
  bbox: [number, number, number, number];
  confidence: number;
  entity_ids: string[];
  resolution_status: string;
  matched_asset_id: string | null;
  coordinates_available: boolean;
  review_status: string;
};

type Workspace = {
  document: {
    id: string;
    project_id: string;
    filename: string;
    processing_status: string;
  };
  pages: number;
  items: Evidence[];
  total: number;
  page_width: number | null;
  page_height: number | null;
};

type AssetOption = { id: string; name: string; longitude: number | null; latitude: number | null };

export default function PdfReviewWorkspace() {
  const { documentId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [page, setPage] = useState(() => Math.max(1, Number(new URLSearchParams(location.search).get("page")) || 1));
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [minConfidence, setMinConfidence] = useState(0);
  const [selected, setSelected] = useState<Evidence | null>(null);
  const [assets, setAssets] = useState<AssetOption[]>([]);
  const [assetId, setAssetId] = useState("");
  const [reason, setReason] = useState("Verified against project map");
  const [reviewer, setReviewer] = useState("TelecomOS reviewer");
  const [error, setError] = useState("");

  async function refresh() {
    if (!documentId) return;
    try {
      setError("");
      const response = await api.get<Workspace>(`/pdf-pole-extractions/${documentId}/workspace`, {
        params: {
          page,
          evidence_type: typeFilter || undefined,
          resolution_status: statusFilter || undefined,
          min_confidence: minConfidence || undefined,
          limit: 500,
        },
      });
      setWorkspace(response.data);
      setSelected((current) => response.data.items.find((item) => item.id === current?.id) ?? response.data.items[0] ?? null);
      const assetsResponse = await api.get<AssetOption[]>("/assets", {
        params: { project_id: response.data.document.project_id, asset_type: "POLE" },
      });
      setAssets(assetsResponse.data);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load PDF review workspace.");
    }
  }

  useEffect(() => {
    refresh().catch(console.error);
  }, [documentId, page, typeFilter, statusFilter, minConfidence]);

  const nearbyPages = useMemo(() => {
    const count = workspace?.pages ?? 1;
    const start = Math.max(1, Math.min(page - 4, count - 8));
    return Array.from({ length: Math.min(9, count) }, (_, index) => start + index);
  }, [page, workspace?.pages]);

  const neighboringSpans = workspace?.items.filter((item) =>
    item.type === "SPAN" && selected && [item.from_pole_id, item.to_pole_id].includes(selected.pole_id),
  ) ?? [];

  async function manualMatch() {
    const entityId = selected?.entity_ids[0];
    if (!entityId || !assetId) return;
    await api.patch(`/pole-entities/${entityId}/manual-match`, {
      asset_id: assetId,
      reason,
      reviewer,
    });
    await refresh();
  }

  async function unmatch() {
    const entityId = selected?.entity_ids[0];
    if (!entityId) return;
    await api.patch(`/pole-entities/${entityId}/unmatch`, { reason, reviewer });
    await refresh();
  }

  async function markNeedsReview() {
    if (!selected) return;
    await api.patch(`/pdf-pole-extractions/${documentId}/evidence/${selected.id}/review`, {
      status: "NEEDS_REVIEW",
    });
    await refresh();
  }

  const pageWidth = workspace?.page_width || 1;
  const pageHeight = workspace?.page_height || 1;

  return (
    <section className="pdf-review-workspace" data-testid="pdf-review-workspace">
      <aside className="panel pdf-review-left">
        <h2>PDF Review</h2>
        <p>{workspace?.document.filename ?? "Loading document..."}</p>
        <div className="pdf-page-controls" aria-label="PDF pages">
          <button onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page === 1}>‹</button>
          {nearbyPages.map((number) => (
            <button key={number} className={number === page ? "selected" : ""} onClick={() => setPage(number)}>{number}</button>
          ))}
          <button onClick={() => setPage((value) => Math.min(workspace?.pages ?? value, value + 1))} disabled={page === workspace?.pages}>›</button>
        </div>
        <div className="pdf-filters">
          <select aria-label="Evidence type" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
            <option value="">All evidence</option><option value="POLE_ID">Poles</option><option value="SPAN">Spans</option><option value="ANCHOR">Anchors</option>
          </select>
          <select aria-label="Resolution status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">All matches</option><option value="RESOLVED">Matched</option><option value="UNRESOLVED">Unmatched</option><option value="AMBIGUOUS">Ambiguous</option><option value="MANUAL">Manual</option>
          </select>
          <label>Confidence ≥ {minConfidence.toFixed(2)}<input aria-label="Minimum confidence" type="range" min="0" max="1" step="0.05" value={minConfidence} onChange={(event) => setMinConfidence(Number(event.target.value))} /></label>
        </div>
        <div className="pdf-evidence-list">
          {workspace?.items.map((item) => (
            <button key={item.id} className={selected?.id === item.id ? "selected" : ""} onClick={() => setSelected(item)}>
              <strong>{item.pole_id ?? (item.type === "SPAN" ? `${item.from_pole_id} → ${item.to_pole_id}` : "Anchor")}</strong>
              <span>Page {item.page_number} · {item.resolution_status} · {Math.round(item.confidence * 100)}%</span>
            </button>
          ))}
        </div>
      </aside>

      <article className="panel pdf-viewer-panel">
        {error && <div className="error-banner">{error}</div>}
        <div className="pdf-page-canvas">
          <img src={`${apiBaseUrl}/pdf-pole-extractions/${documentId}/pages/${page}.png`} alt={`PDF page ${page}`} />
          {workspace?.items.map((item) => {
            const [x0, top, x1, bottom] = item.bbox;
            return <button
              aria-label={`Select ${item.type} evidence`}
              key={item.id}
              className={`pdf-bbox ${item.type.toLowerCase()} ${selected?.id === item.id ? "selected" : ""}`}
              style={{ left: `${x0 / pageWidth * 100}%`, top: `${top / pageHeight * 100}%`, width: `${(x1 - x0) / pageWidth * 100}%`, height: `${(bottom - top) / pageHeight * 100}%` }}
              onClick={() => setSelected(item)}
            />;
          })}
        </div>
      </article>

      <aside className="panel pdf-review-inspector">
        <h2>{selected?.pole_id ?? (selected?.type === "SPAN" ? "PDF Span" : "Select evidence")}</h2>
        {selected && <>
          <div className="kv"><span>Page</span><strong>{selected.page_number}</strong></div>
          <div className="kv"><span>Confidence</span><strong>{Math.round(selected.confidence * 100)}%</strong></div>
          <div className="kv"><span>Status</span><strong>{selected.resolution_status}</strong></div>
          <div className="kv"><span>Coordinates</span><strong>{selected.coordinates_available ? "Available" : "Not available"}</strong></div>
          <label className="field-label">Raw text</label><p className="raw-evidence">{selected.raw_text}</p>
          <label className="field-label">Match to Asset</label>
          <select aria-label="Match asset" value={assetId} onChange={(event) => setAssetId(event.target.value)}>
            <option value="">Select project pole…</option>{assets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
          </select>
          <input aria-label="Reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
          <textarea aria-label="Resolution reason" value={reason} onChange={(event) => setReason(event.target.value)} />
          <div className="review-actions">
            <button onClick={manualMatch} disabled={!selected.entity_ids.length || !assetId}>Match to Asset</button>
            <button onClick={unmatch} disabled={!selected.entity_ids.length}>Unmatch</button>
            <button onClick={markNeedsReview}>Mark Needs Review</button>
            <button onClick={() => selected.matched_asset_id && navigate(`/engineering?project_id=${workspace?.document.project_id}&asset_id=${selected.matched_asset_id}`)} disabled={!selected.matched_asset_id}>Open on Map</button>
          </div>
          <h3>Neighboring spans</h3>
          {neighboringSpans.length ? neighboringSpans.map((span) => <button key={span.id} onClick={() => setSelected(span)}>{span.from_pole_id} → {span.to_pole_id}</button>) : <p>No spans on this page.</p>}
        </>}
      </aside>
    </section>
  );
}
