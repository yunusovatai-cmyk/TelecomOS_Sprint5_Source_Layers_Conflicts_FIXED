import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import PdfReviewWorkspace from "./PdfReviewWorkspace";
import { api } from "./services/api";

vi.mock("./services/api", () => ({
  apiBaseUrl: "http://api.test/api/v1",
  api: { get: vi.fn(), patch: vi.fn() },
}));

const matchedEvidence = {
  id: "evidence-1", type: "POLE_ID", page_number: 7, pole_id: "121673073",
  external_eid: null, from_pole_id: null, to_pole_id: null, span_length_ft: null,
  raw_text: "EXIST. POLE #121673073", bbox: [100, 200, 300, 220], confidence: 0.98,
  entity_ids: ["entity-1"], resolution_status: "RESOLVED", matched_asset_id: "asset-1",
  coordinates_available: true, review_status: "OPEN",
};
const unmatchedEvidence = {
  ...matchedEvidence, id: "evidence-2", pole_id: "555555555", raw_text: "POLE #555555555",
  entity_ids: ["entity-2"], resolution_status: "UNRESOLVED", matched_asset_id: null,
  coordinates_available: false,
};

function workspace(items = [matchedEvidence, unmatchedEvidence]) {
  return {
    document: { id: "doc-1", project_id: "project-1", filename: "permit.pdf", processing_status: "PARSED" },
    pages: 141, items, total: items.length, offset: 0, limit: 500,
    page_width: 1224, page_height: 792,
  };
}

function renderWorkspace() {
  return render(
    <MemoryRouter initialEntries={["/pdf-review/doc-1?page=7"]}>
      <Routes>
        <Route path="/pdf-review/:documentId" element={<PdfReviewWorkspace />} />
        <Route path="/engineering" element={<div>Engineering Map destination</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("PDF Review Workspace", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (url === "/assets") return { data: [{ id: "asset-1", name: "Pole #121673073", longitude: -121, latitude: 39 }] } as never;
      return { data: workspace() } as never;
    });
    vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders the route and selects PDF evidence", async () => {
    renderWorkspace();
    expect(await screen.findByTestId("pdf-review-workspace")).toBeTruthy();
    expect(await screen.findByText("EXIST. POLE #121673073")).toBeTruthy();

    await userEvent.click(screen.getByText("555555555"));
    expect(screen.getByText("POLE #555555555")).toBeTruthy();
  });

  it("requests matched and unmatched filters", async () => {
    renderWorkspace();
    await screen.findAllByText("121673073");
    await userEvent.selectOptions(screen.getByLabelText("Resolution status"), "UNRESOLVED");

    await waitFor(() => expect(api.get).toHaveBeenCalledWith(
      "/pdf-pole-extractions/doc-1/workspace",
      expect.objectContaining({ params: expect.objectContaining({ resolution_status: "UNRESOLVED" }) }),
    ));
  });

  it("opens the matched asset on Engineering Map", async () => {
    renderWorkspace();
    await screen.findByText("EXIST. POLE #121673073");
    await userEvent.click(screen.getByRole("button", { name: "Open on Map" }));
    expect(await screen.findByText("Engineering Map destination")).toBeTruthy();
  });

  it("submits the manual match form", async () => {
    renderWorkspace();
    await screen.findByText("EXIST. POLE #121673073");
    await userEvent.selectOptions(screen.getByLabelText("Match asset"), "asset-1");
    fireEvent.change(screen.getByLabelText("Reviewer"), { target: { value: "reviewer@example.com" } });
    fireEvent.change(screen.getByLabelText("Resolution reason"), { target: { value: "Field verified" } });
    await userEvent.click(screen.getByRole("button", { name: "Match to Asset" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      "/pole-entities/entity-1/manual-match",
      { asset_id: "asset-1", reason: "Field verified", reviewer: "reviewer@example.com" },
    ));
  });
});
