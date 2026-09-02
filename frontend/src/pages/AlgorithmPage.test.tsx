import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AlgorithmContent } from "./AlgorithmPage";
import * as algorithmApi from "../api/algorithm";
import type { AlgorithmJob } from "../api/algorithm";
import * as dutyConfigApi from "../api/dutyConfig";
import * as soldiersApi from "../api/soldiers";
import * as shiftsApi from "../api/shifts";
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
    markJobSeen: vi.fn(),
    markAllJobsSeen: vi.fn(),
  };
});
vi.mock("../api/dutyConfig");
vi.mock("../api/soldiers");
vi.mock("../api/shifts", async () => {
  const actual = await vi.importActual<typeof import("../api/shifts")>("../api/shifts");
  return { ...actual, listShifts: vi.fn() };
});

function renderPage(initialJobId?: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AlgorithmSeenProvider>
          <AlgorithmContent initialJobId={initialJobId} />
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
  vi.mocked(shiftsApi.listShifts).mockResolvedValue([]);
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

describe("AlgorithmPage - returned job review", () => {
  it("opens the exact submitted job directly at its proposal review", async () => {
    const reviewJob: AlgorithmJob = {
      id: "returned-job-42",
      status: "done",
      mode: "shadow",
      planning_start: "2026-09-10",
      planning_end: "2026-09-11",
      started_at: null,
      finished_at: null,
      error_message: null,
      progress_message: null,
      solver_metrics: {},
      relaxed: [],
      reasons: [],
      batch_results: [],
      result_metadata: null,
      proposals: [{
        assignment_id: "returned-assignment-1",
        soldier_id: "soldier-1",
        duty_type_id: "type-1",
        duty_location_id: "location-1",
        start_date: "2026-09-10",
        end_date: "2026-09-10",
        status: "algorithm_draft",
        reserve_soldier_id: null,
        norm_score_before: null,
        norm_score_after: null,
        duty_shift_id: "shift-1",
        candidate_rank: null,
        candidate_pool_size: null,
        batch_index: null,
      }],
    };
    vi.mocked(algorithmApi.listJobs).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(algorithmApi.pollJob).mockResolvedValue(reviewJob);

    renderPage("returned-job-42");

    await waitFor(() => expect(algorithmApi.pollJob).toHaveBeenCalledWith("returned-job-42"));
    expect(await screen.findByTestId("algorithm-job-review-returned-job-42")).toBeVisible();
    expect(await screen.findByTestId("algorithm-proposal-review")).toBeVisible();
    expect(screen.getByTestId("algorithm-proposal-returned-assignment-1")).toBeVisible();
  });
});
