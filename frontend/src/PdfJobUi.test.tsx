import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ImportCenter } from "./App";
import { api } from "./services/api";

vi.mock("./services/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

const queued = {
  id: "job-1", project_id: "project-1", document_id: "document-1",
  status: "QUEUED", stage: "QUEUED", progress: 0, error_message: null,
};

describe("background PDF job UI", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); });

  it("uploads without blocking and displays polling state", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: queued } as never);
    render(<MemoryRouter><ImportCenter projectId="project-1" onImported={vi.fn()} /></MemoryRouter>);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["%PDF-1.4"], "permit.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: "Process PDF in background" }));
    expect((await screen.findByTestId("pdf-job-status")).textContent).toContain("QUEUED");
    expect(localStorage.getItem("telecomos:pdf-job:project-1")).toBe("job-1");
  });

  it("restores a failed job and retries it", async () => {
    localStorage.setItem("telecomos:pdf-job:project-1", "job-1");
    vi.mocked(api.get).mockResolvedValue({ data: { ...queued, status: "FAILED", stage: "FAILED", error_message: "Safe error" } } as never);
    vi.mocked(api.post).mockResolvedValue({ data: queued } as never);
    render(<MemoryRouter><ImportCenter projectId="project-1" onImported={vi.fn()} /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "/pdf-jobs/job-1/retry", null, { params: { project_id: "project-1" } },
    ));
  });
});
