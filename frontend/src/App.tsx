import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BrowserRouter,
  NavLink,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from "react-leaflet";
import { api } from "./services/api";
import "./styles.css";
import "leaflet/dist/leaflet.css";

type Project = {
  id: string;
  project_code: string;
  name: string;
  status: string;
};

type Asset = {
  id: string;
  project_id: string;
  asset_type: string;
  name: string;
  status: string;
  longitude: number | null;
  latitude: number | null;
  geometry_type: string;
  geometry_json: string | null;
  issue: string | null;
  source_document_id: string | null;
};


type Conflict = {
  id: string;
  project_id: string;
  object_key: string;
  conflict_type: string;
  severity: string;
  status: string;
  summary: string;
  details_json: string;
  decision: string | null;
  decision_reason: string | null;
};

type AppState = {
  projects: Project[];
  assets: Asset[];
  selectedProjectId: string;
  selectedAsset: Asset | null;
  loading: boolean;
  error: string;
  search: string;
  typeFilter: string;
  statusFilter: string;
  conflicts: Conflict[];
};

function Layout() {
  const navigate = useNavigate();
  const [state, setState] = useState<AppState>({
    projects: [],
    assets: [],
    selectedProjectId: "",
    selectedAsset: null,
    loading: false,
    error: "",
    search: "",
    typeFilter: "",
    statusFilter: "",
    conflicts: [],
  });

  const refresh = useCallback(async (projectId?: string) => {
    setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const projectsResponse = await api.get<Project[]>("/projects");
      const projects = projectsResponse.data;
      const chosenProject =
        projectId ||
        state.selectedProjectId ||
        projects[0]?.id ||
        "";
      const assetsResponse = await api.get<Asset[]>("/assets", {
        params: chosenProject ? { project_id: chosenProject } : {},
      });
      const conflictsResponse = chosenProject
        ? await api.get<Conflict[]>("/conflicts", { params: { project_id: chosenProject } })
        : { data: [] as Conflict[] };

      setState((current) => ({
        ...current,
        projects,
        assets: assetsResponse.data,
        conflicts: conflictsResponse.data,
        selectedProjectId: chosenProject,
        selectedAsset:
          current.selectedAsset &&
          assetsResponse.data.some((asset) => asset.id === current.selectedAsset?.id)
            ? current.selectedAsset
            : null,
        loading: false,
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to load data.";
      setState((current) => ({ ...current, loading: false, error: message }));
    }
  }, [state.selectedProjectId]);

  useEffect(() => {
    refresh().catch(console.error);
  }, []);

  async function loadDemo() {
    setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const response = await api.post<{ project: Project; assets: Asset[] }>("/demo/load");
      const project = response.data.project;
      await refresh(project.id);
      navigate("/engineering");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Demo load failed.";
      setState((current) => ({ ...current, loading: false, error: message }));
    }
  }

  async function createProject(code: string, name: string) {
    await api.post<Project>("/projects", { project_code: code, name });
    await refresh();
  }

  async function changeProject(projectId: string) {
    setState((current) => ({
      ...current,
      selectedProjectId: projectId,
      selectedAsset: null,
    }));
    await refresh(projectId);
  }


  async function rebuildConflicts() {
    if (!state.selectedProjectId) return;
    const response = await api.post<Conflict[]>("/conflicts/rebuild", null, {
      params: { project_id: state.selectedProjectId },
    });
    setState((current) => ({ ...current, conflicts: response.data }));
  }

  async function decideConflict(
    conflictId: string,
    decision: "AERIAL" | "UG" | "NEEDS_REVIEW",
    reason: string,
  ) {
    const response = await api.patch<Conflict>(`/conflicts/${conflictId}`, {
      decision,
      decision_reason: reason || null,
    });
    setState((current) => ({
      ...current,
      conflicts: current.conflicts.map((item) =>
        item.id === response.data.id ? response.data : item,
      ),
    }));
  }

async function updateAsset(
  assetId: string,
  changes: Partial<Pick<Asset, "status" | "issue" | "name">>,
) {
  const response = await api.patch<Asset>(`/assets/${assetId}`, changes);
  setState((current) => ({
    ...current,
    assets: current.assets.map((asset) =>
      asset.id === response.data.id ? response.data : asset,
    ),
    selectedAsset: response.data,
  }));
}

const filteredAssets = useMemo(() => {
  const query = state.search.trim().toLowerCase();
  return state.assets.filter((asset) => {
    const matchesSearch =
      !query ||
      asset.name.toLowerCase().includes(query) ||
      (asset.issue ?? "").toLowerCase().includes(query);

    const matchesType =
      !state.typeFilter || asset.asset_type === state.typeFilter;

    const matchesStatus =
      !state.statusFilter || asset.status === state.statusFilter;

    return matchesSearch && matchesType && matchesStatus;
  });
}, [state.assets, state.search, state.typeFilter, state.statusFilter]);

  const selectedProject = useMemo(
    () => state.projects.find((project) => project.id === state.selectedProjectId),
    [state.projects, state.selectedProjectId],
  );

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">TelecomOS</div>
        <div className="version">Sprint 1</div>

        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/projects">Projects</NavLink>
          <NavLink to="/engineering">Engineering Map</NavLink>
          <NavLink to="/import">Import Center</NavLink>
          <NavLink to="/review">Review Queue</NavLink>
        </nav>

        <div className="sidebar-footer">
          <span>Project</span>
          <select
            value={state.selectedProjectId}
            onChange={(event) => changeProject(event.target.value)}
          >
            <option value="">No project selected</option>
            {state.projects.map((project) => (
              <option value={project.id} key={project.id}>
                {project.project_code}
              </option>
            ))}
          </select>
        </div>
      </aside>

      <main>
        <header>
          <div>
            <h1>{selectedProject?.name ?? "TelecomOS Platform"}</h1>
            <p>Projects, map, assets and engineering review</p>
          </div>
          <div className="header-actions">
            <button className="demo-button" onClick={loadDemo} disabled={state.loading}>
              {state.loading ? "Working..." : "Load Demo Project"}
            </button>
            <button onClick={() => refresh()} disabled={state.loading}>Refresh</button>
            <span className="status">SYSTEM ONLINE</span>
          </div>
        </header>

        {state.error && <div className="error-banner">{state.error}</div>}

        <Routes>
          <Route
            path="/"
            element={
              <Dashboard
                projects={state.projects}
                assets={state.assets}
                onCreate={createProject}
              />
            }
          />
          <Route
            path="/projects"
            element={
              <ProjectsPage
                projects={state.projects}
                selectedProjectId={state.selectedProjectId}
                onSelect={changeProject}
                onCreate={createProject}
              />
            }
          />
          <Route
            path="/engineering"
            element={
              <EngineeringMap
                assets={filteredAssets}
                selectedAsset={state.selectedAsset}
                search={state.search}
                typeFilter={state.typeFilter}
                statusFilter={state.statusFilter}
                onSearch={(value) =>
                  setState((current) => ({ ...current, search: value }))
                }
                onTypeFilter={(value) =>
                  setState((current) => ({ ...current, typeFilter: value }))
                }
                onStatusFilter={(value) =>
                  setState((current) => ({ ...current, statusFilter: value }))
                }
                onSelect={(asset) =>
                  setState((current) => ({ ...current, selectedAsset: asset }))
                }
                conflicts={state.conflicts}
                onRebuildConflicts={rebuildConflicts}
                onDecideConflict={decideConflict}
                onUpdate={updateAsset}
              />
            }
          />
          <Route path="/import" element={<ImportCenter onImported={async (projectId) => { await refresh(projectId); navigate("/engineering"); }} />} />
          <Route
            path="/review"
            element={
              <ReviewQueue
                assets={state.assets.filter((asset) => asset.status === "REVIEW")}
                onOpen={(asset) => {
                  setState((current) => ({ ...current, selectedAsset: asset }));
                  navigate("/engineering");
                }}
              />
            }
          />
        </Routes>
      </main>
    </div>
  );
}

function Dashboard({
  projects,
  assets,
  onCreate,
}: {
  projects: Project[];
  assets: Asset[];
  onCreate: (code: string, name: string) => Promise<void>;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");

  async function submit() {
    if (!code.trim() || !name.trim()) return;
    await onCreate(code.trim(), name.trim());
    setCode("");
    setName("");
  }

  return (
    <>
      <section className="stats">
        <article><span>Projects</span><strong>{projects.length}</strong></article>
        <article><span>Assets</span><strong>{assets.length}</strong></article>
        <article><span>Review</span><strong>{assets.filter((a) => a.status === "REVIEW").length}</strong></article>
        <article><span>Verified</span><strong>{assets.filter((a) => a.status === "VERIFIED").length}</strong></article>
      </section>

      <section className="grid dashboard-grid">
        <article className="panel">
          <h2>Create Project</h2>
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Project code" />
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name" />
          <button onClick={submit}>Create Project</button>
        </article>
        <article className="panel">
          <h2>Platform Foundation</h2>
          <div className="system-grid">
            <div><span>Database</span><strong>PostGIS</strong></div>
            <div><span>Storage</span><strong>MinIO</strong></div>
            <div><span>Queue</span><strong>Redis</strong></div>
            <div><span>API</span><strong>FastAPI</strong></div>
          </div>
        </article>
      </section>
    </>
  );
}

function ProjectsPage({
  projects,
  selectedProjectId,
  onSelect,
  onCreate,
}: {
  projects: Project[];
  selectedProjectId: string;
  onSelect: (id: string) => Promise<void>;
  onCreate: (code: string, name: string) => Promise<void>;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");

  return (
    <section className="grid projects-grid">
      <article className="panel">
        <h2>New Project</h2>
        <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Project code" />
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name" />
        <button
          onClick={async () => {
            if (!code.trim() || !name.trim()) return;
            await onCreate(code.trim(), name.trim());
            setCode("");
            setName("");
          }}
        >
          Create Project
        </button>
      </article>

      <article className="panel">
        <h2>Projects</h2>
        {projects.length === 0 && <p>No projects yet.</p>}
        {projects.map((project) => (
          <button
            className={`project-row ${project.id === selectedProjectId ? "selected" : ""}`}
            key={project.id}
            onClick={() => onSelect(project.id)}
          >
            <div>
              <strong>{project.project_code}</strong>
              <span>{project.name}</span>
            </div>
            <b>{project.status}</b>
          </button>
        ))}
      </article>
    </section>
  );
}

function EngineeringMap({
  assets,
  selectedAsset,
  search,
  typeFilter,
  statusFilter,
  onSearch,
  onTypeFilter,
  onStatusFilter,
  onSelect,
  conflicts,
  onRebuildConflicts,
  onDecideConflict,
  onUpdate,
}: {
  assets: Asset[];
  selectedAsset: Asset | null;
  search: string;
  typeFilter: string;
  statusFilter: string;
  onSearch: (value: string) => void;
  onTypeFilter: (value: string) => void;
  onStatusFilter: (value: string) => void;
  onSelect: (asset: Asset) => void;
  conflicts: Conflict[];
  onRebuildConflicts: () => Promise<void>;
  onDecideConflict: (
    conflictId: string,
    decision: "AERIAL" | "UG" | "NEEDS_REVIEW",
    reason: string,
  ) => Promise<void>;
  onUpdate: (
    assetId: string,
    changes: Partial<Pick<Asset, "status" | "issue" | "name">>,
  ) => Promise<void>;
}) {
  const center: [number, number] = assets.find(
    (asset) => asset.latitude !== null && asset.longitude !== null,
  )
    ? [
        assets.find((asset) => asset.latitude !== null)!.latitude!,
        assets.find((asset) => asset.longitude !== null)!.longitude!,
      ]
    : [39.01076, -121.61118];

  const [draftIssue, setDraftIssue] = useState("");
  const [decisionReason, setDecisionReason] = useState("");

  useEffect(() => {
    setDraftIssue(selectedAsset?.issue ?? "");
  }, [selectedAsset]);

  const reviewItems = assets.filter((asset) => asset.status === "REVIEW");

  return (
    <>
      <section className="map-toolbar panel">
        <input
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder="Search pole, EID, issue..."
        />
        <select value={typeFilter} onChange={(event) => onTypeFilter(event.target.value)}>
          <option value="">All asset types</option>
          <option value="POLE">Pole</option>
          <option value="HANDHOLE">Handhole</option>
          <option value="UG_SEGMENT">UG</option>
          <option value="AERIAL_SPAN">Aerial</option>
        </select>
        <select value={statusFilter} onChange={(event) => onStatusFilter(event.target.value)}>
          <option value="">All statuses</option>
          <option value="REVIEW">Review</option>
          <option value="APPROVED">Approved</option>
          <option value="REJECTED">Rejected</option>
          <option value="VERIFIED">Verified</option>
        </select>
        <button onClick={onRebuildConflicts}>Detect Conflicts</button>
        <strong>{assets.length} visible · {conflicts.filter((c) => c.status === "OPEN").length} conflicts</strong>
      </section>

      <section className="workspace">
        <aside className="panel review-panel">
          <h2>Review Queue</h2>
          <p>{reviewItems.length} objects</p>
          <div className="review-list">
            {reviewItems.slice(0, 500).map((asset) => (
              <button key={asset.id} onClick={() => onSelect(asset)}>
                <strong>{asset.name}</strong>
                <span>{asset.issue ?? "Needs review"}</span>
              </button>
            ))}
          </div>
        </aside>

        <article className="panel map-panel">
          <div className="panel-heading">
            <div>
              <h2>Engineering Map</h2>
              <p>Click an object to review and update it</p>
            </div>
            <div className="legend">
              <span><i className="pole" />Pole</span>
              <span><i className="hh" />HH</span>
              <span><i className="ug" />UG</span>
              <span><i className="aerial" />Aerial</span>
            </div>
          </div>

          <MapContainer center={center} zoom={15} className="leaflet-map">
            <TileLayer
              attribution="&copy; OpenStreetMap contributors"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {assets.map((asset) => {
              if (
                asset.geometry_type === "Point" &&
                asset.latitude !== null &&
                asset.longitude !== null
              ) {
                const color =
                  asset.status === "APPROVED"
                    ? "#34d17c"
                    : asset.status === "REJECTED"
                      ? "#ff5f73"
                      : asset.status === "VERIFIED"
                        ? "#4ca6ff"
                        : "#ffbd52";

                return (
                  <CircleMarker
                    key={asset.id}
                    center={[asset.latitude, asset.longitude]}
                    radius={6}
                    pathOptions={{ color: "#ffffff", fillColor: color, fillOpacity: 0.95 }}
                    eventHandlers={{ click: () => onSelect(asset) }}
                  >
                    <Tooltip>{asset.name}</Tooltip>
                  </CircleMarker>
                );
              }

              if (asset.geometry_type === "LineString" && asset.geometry_json) {
                const parsed = JSON.parse(asset.geometry_json) as {
                  coordinates: [number, number][];
                };
                const positions = parsed.coordinates.map(
                  ([lon, lat]) => [lat, lon] as [number, number],
                );
                return (
                  <Polyline
                    key={asset.id}
                    positions={positions}
                    pathOptions={{
                      color:
                        asset.status === "REJECTED"
                          ? "#ff5f73"
                          : asset.asset_type === "UG_SEGMENT"
                            ? "#9b78ff"
                            : "#4ca6ff",
                      weight: 5,
                      dashArray: asset.asset_type === "UG_SEGMENT" ? "10 7" : undefined,
                    }}
                    eventHandlers={{ click: () => onSelect(asset) }}
                  >
                    <Tooltip>{asset.name}</Tooltip>
                  </Polyline>
                );
              }
              return null;
            })}
          </MapContainer>
        </article>

        <aside className="panel inspector">
          <h2>{selectedAsset?.name ?? "Select an object"}</h2>
          {!selectedAsset ? (
            <p>Click a map object or review item.</p>
          ) : (
            <>
              <div className="kv"><span>Type</span><strong>{selectedAsset.asset_type}</strong></div>
              <div className="kv"><span>Status</span><strong>{selectedAsset.status}</strong></div>
              <div className="kv"><span>Latitude</span><strong>{selectedAsset.latitude ?? "—"}</strong></div>
              <div className="kv"><span>Longitude</span><strong>{selectedAsset.longitude ?? "—"}</strong></div>
              <div className="kv"><span>Geometry</span><strong>{selectedAsset.geometry_type}</strong></div>

              <label className="field-label">Engineer notes</label>
              <textarea
                value={draftIssue}
                onChange={(event) => setDraftIssue(event.target.value)}
                placeholder="Add engineering notes..."
              />

              <div className="review-actions">
                <button
                  className="approve"
                  onClick={() =>
                    onUpdate(selectedAsset.id, {
                      status: "APPROVED",
                      issue: draftIssue || null,
                    })
                  }
                >
                  Approve
                </button>
                <button
                  className="reject"
                  onClick={() =>
                    onUpdate(selectedAsset.id, {
                      status: "REJECTED",
                      issue: draftIssue || "Rejected by engineer",
                    })
                  }
                >
                  Reject
                </button>
                <button
                  onClick={() =>
                    onUpdate(selectedAsset.id, {
                      status: "REVIEW",
                      issue: draftIssue || "Requires engineering review",
                    })
                  }
                >
                  Return to Review
                </button>
              </div>
            </>
          )}
        </aside>
      </section>

      <section className="panel conflict-panel">
        <div className="panel-heading">
          <div>
            <h2>Source Conflicts</h2>
            <p>Conflicting construction variants from different documents.</p>
          </div>
        </div>

        {conflicts.length === 0 ? (
          <p>No conflicts detected yet. Click Detect Conflicts.</p>
        ) : (
          <div className="conflict-list">
            {conflicts.map((conflict) => {
              const details = JSON.parse(conflict.details_json) as {
                sources: Array<{
                  asset_type: string;
                  asset_name: string;
                  document_name: string | null;
                  revision: string | null;
                }>;
              };

              return (
                <article key={conflict.id} className={conflict.status === "RESOLVED" ? "resolved" : ""}>
                  <div>
                    <span className="severity">{conflict.severity}</span>
                    <strong>{conflict.summary}</strong>
                    {details.sources.map((source, index) => (
                      <small key={`${source.asset_name}-${index}`}>
                        {source.asset_type} · {source.document_name ?? "Unknown source"}
                        {source.revision ? ` · Rev ${source.revision}` : ""}
                      </small>
                    ))}
                  </div>

                  <textarea
                    value={decisionReason}
                    onChange={(event) => setDecisionReason(event.target.value)}
                    placeholder="Reason for engineering decision"
                  />

                  <div className="conflict-actions">
                    <button onClick={() => onDecideConflict(conflict.id, "AERIAL", decisionReason)}>
                      Choose Aerial
                    </button>
                    <button onClick={() => onDecideConflict(conflict.id, "UG", decisionReason)}>
                      Choose UG
                    </button>
                    <button onClick={() => onDecideConflict(conflict.id, "NEEDS_REVIEW", decisionReason)}>
                      Needs Review
                    </button>
                  </div>

                  {conflict.decision && (
                    <b>Decision: {conflict.decision}</b>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </>
  );
}
function ImportCenter({
  onImported,
}: {
  onImported: (projectId: string) => Promise<void>;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [projectName, setProjectName] = useState("");
  const [working, setWorking] = useState(false);
  const [report, setReport] = useState<any>(null);
  const [error, setError] = useState("");

  async function uploadPackage() {
    if (!files.length) {
      setError("Select project files first.");
      return;
    }
    setWorking(true);
    setError("");
    try {
      const form = new FormData();
      files.forEach((file) => form.append("files", file));
      if (projectName.trim()) form.append("project_name", projectName.trim());
      const response = await api.post("/package-imports", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setReport(response.data);
      await onImported(response.data.project.id);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Package import failed.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="import-layout">
      <article className="panel import-panel">
        <h2>Project Package Import</h2>
        <p>Load KMZ, KML, permits, PRM, Make Ready, spreadsheets and photos into one project.</p>
        <input value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="Project name" />
        <label className="file-drop">
          <input type="file" multiple accept=".kmz,.kml,.pdf,.xlsx,.xls,.csv,.jpg,.jpeg,.png,.zip"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
          <strong>{files.length ? `${files.length} files selected` : "Choose project files"}</strong>
          <span>Each file is registered separately. GIS files create map assets.</span>
        </label>
        {files.length > 0 && (
          <div className="selected-files">
            {files.slice(0, 12).map((file) => <span key={`${file.name}-${file.size}`}>{file.name}</span>)}
            {files.length > 12 && <span>+{files.length - 12} more</span>}
          </div>
        )}
        {error && <div className="error-banner">{error}</div>}
        <button onClick={uploadPackage} disabled={!files.length || working}>
          {working ? "Analyzing package..." : "Import Project Package"}
        </button>
      </article>

      <article className="panel">
        <h2>Document Registry</h2>
        {!report ? <p>The classified document registry will appear here.</p> : (
          <>
            <div className="report-grid">
              <div><span>Project</span><strong>{report.project.name}</strong></div>
              <div><span>Documents</span><strong>{report.documents_registered}</strong></div>
              <div><span>Assets created</span><strong>{report.assets_created}</strong></div>
              <div><span>Warnings</span><strong>{report.warnings.length}</strong></div>
            </div>
            <h3>Document types</h3>
            {Object.entries(report.document_types).map(([type, count]) => (
              <div className="kv" key={type}><span>{type}</span><strong>{String(count)}</strong></div>
            ))}
            <h3>Files</h3>
            <div className="document-list">
              {report.documents.map((document: any) => (
                <div key={document.id}>
                  <strong>{document.filename}</strong>
                  <span>{document.document_type}{document.revision ? ` · Rev ${document.revision}` : ""}{document.duplicate ? " · Duplicate" : ""}{document.assets_created ? ` · ${document.assets_created} assets` : ""}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </article>
    </section>
  );
}
function ReviewQueue({
  assets,
  onOpen,
}: {
  assets: Asset[];
  onOpen: (asset: Asset) => void;
}) {
  return (
    <section className="panel">
      <h2>Review Queue</h2>
      {assets.length === 0 && <p>No open review items.</p>}
      <div className="review-table">
        {assets.map((asset) => (
          <button key={asset.id} onClick={() => onOpen(asset)}>
            <span className="severity">HIGH</span>
            <div>
              <strong>{asset.name}</strong>
              <span>{asset.issue ?? "Requires engineering review"}</span>
            </div>
            <b>Open on map</b>
          </button>
        ))}
      </div>
    </section>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  );
}
