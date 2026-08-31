import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AlgorithmContent } from "./AlgorithmPage";
import * as algorithmApi from "../api/algorithm";
import * as dutyConfigApi from "../api/dutyConfig";
import * as soldiersApi from "../api/soldiers";
import { AlgorithmSeenProvider } from "../contexts/AlgorithmSeenContext";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../api/algorithm", async () => {
  const actual = await vi.importActual<typeof import("../api/algorithm")>("../api/algorithm");
  return {
    ...actual,
    listJobs: vi.fn(),
    pollJob: vi.fn(),
    cancelJob: vi.fn(),
  };
});
vi.mock("../api/dutyConfig");
vi.mock("../api/soldiers");

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AlgorithmSeenProvider>
          <AlgorithmContent />
        </AlgorithmSeenProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const job = {
  id: "job-1",
  status: "done" as const,
  mode: "shadow",
  planning_start: "2026-01-01",
  planning_end: "2026-01-02",
  shift_count: 2,
  created_at: "2026-01-01",
  started_at: null,
  finished_at: null,
  error_message: null,
  total_duties: 0,
  assigned_duties: 0,
  seen: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([]);
  vi.mocked(soldiersApi.listSoldiers).mockResolvedValue([]);
});

describe("AlgorithmPage - job list load error", () => {
  it("shows a load error instead of the empty-state copy when the job list fails to load", async () => {
    vi.mocked(algorithmApi.listJobs).mockRejectedValue(new Error("jobs unavailable"));

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("algorithm.jobs_load_error");
    expect(screen.queryByText("algorithm.no_runs")).not.toBeInTheDocument();
  });

  it("keeps the empty-state copy for a genuinely empty job list", async () => {
    vi.mocked(algorithmApi.listJobs).mockResolvedValue({ items: [], total: 0 });

    renderPage();

    expect(await screen.findByText("algorithm.no_runs")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("AlgorithmPage - selected job load error", () => {
  it("shows a load error instead of an infinite loading spinner when the selected job fails to load", async () => {
    vi.mocked(algorithmApi.listJobs).mockResolvedValue({ items: [job], total: 1 });
    vi.mocked(algorithmApi.pollJob).mockRejectedValue(new Error("Invalid algorithm job response"));

    renderPage();

    const jobButton = await screen.findByText(/2026-01-01/);
    fireEvent.click(jobButton);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("algorithm.job_load_error");
    });
    expect(screen.queryByText("app.loading")).not.toBeInTheDocument();
  });
});
