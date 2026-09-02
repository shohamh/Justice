import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ShiftsManagementPage from "./ShiftsManagementPage";
import { AlgorithmSeenProvider } from "../../contexts/AlgorithmSeenContext";

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../ShiftsPage", () => ({
  ShiftsContent: ({ onJobSubmitted }: { onJobSubmitted?: (jobId: string) => void }) => (
    <button type="button" data-testid="shifts-content" onClick={() => onJobSubmitted?.("returned-job-42")}>submit inline job</button>
  ),
}));

vi.mock("../ShiftTemplatesPage", () => ({
  ShiftTemplatesContent: () => <div data-testid="templates-content" />,
}));

vi.mock("../AlgorithmPage", () => ({
  AlgorithmContent: () => <div data-testid="algorithm-content" />,
}));

const mockListJobs = vi.fn();
vi.mock("../../api/algorithm", () => ({
  listJobs: (...args: unknown[]) => mockListJobs(...args),
  markJobSeen: vi.fn(),
  markAllJobsSeen: vi.fn(),
}));

function job(status: string, mode: string, error_message: string | null = null) {
  return { status, mode, error_message, id: `job-${Math.random()}`, seen: false };
}

describe("ShiftsManagementPage — algorithm run badges", () => {
  beforeEach(() => {
    mockListJobs.mockReset();
  });

  test("renders no badges when there are no jobs", async () => {
    mockListJobs.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(
      <AlgorithmSeenProvider>
        <ShiftsManagementPage />
      </AlgorithmSeenProvider>
    );
    await waitFor(() => expect(mockListJobs).toHaveBeenCalled());
    expect(screen.queryByTestId("algo-badge-running")).not.toBeInTheDocument();
    expect(screen.queryByTestId("algo-badge-draft")).not.toBeInTheDocument();
    expect(screen.queryByTestId("algo-badge-done")).not.toBeInTheDocument();
    expect(screen.queryByTestId("algo-badge-failed")).not.toBeInTheDocument();
  });

  test("groups jobs into running/draft/done/failed by status and mode", async () => {
    mockListJobs.mockResolvedValue({
      items: [
        job("pending", "shadow"),
        job("running", "dm_reviewed"),
        job("done", "shadow"),
        job("done", "shadow"),
        job("done", "dm_reviewed"),
        job("failed", "shadow"),
      ],
      total: 6,
    });
    renderWithProviders(
      <AlgorithmSeenProvider>
        <ShiftsManagementPage />
      </AlgorithmSeenProvider>
    );

    expect(await screen.findByTestId("algo-badge-running")).toHaveTextContent("2");
    expect(await screen.findByTestId("algo-badge-draft")).toHaveTextContent("2");
    expect(await screen.findByTestId("algo-badge-done")).toHaveTextContent("1");
    expect(await screen.findByTestId("algo-badge-failed")).toHaveTextContent("1");
  });

  test("omits a badge when its group count is zero", async () => {
    mockListJobs.mockResolvedValue({
      items: [job("pending", "shadow")],
      total: 1,
    });
    renderWithProviders(
      <AlgorithmSeenProvider>
        <ShiftsManagementPage />
      </AlgorithmSeenProvider>
    );

    expect(await screen.findByTestId("algo-badge-running")).toHaveTextContent("1");
    expect(screen.queryByTestId("algo-badge-draft")).not.toBeInTheDocument();
    expect(screen.queryByTestId("algo-badge-done")).not.toBeInTheDocument();
    expect(screen.queryByTestId("algo-badge-failed")).not.toBeInTheDocument();
  });

  test("excludes a cancelled job from the failed badge", async () => {
    mockListJobs.mockResolvedValue({
      items: [
        job("failed", "shadow", "cancelled_by_user"),
        job("failed", "dm_reviewed", "solver_timeout"),
      ],
      total: 2,
    });
    renderWithProviders(
      <AlgorithmSeenProvider>
        <ShiftsManagementPage />
      </AlgorithmSeenProvider>
    );

    expect(await screen.findByTestId("algo-badge-failed")).toHaveTextContent("1");
  });

  test("opens a stable review boundary for the exact job returned by the inline run", async () => {
    mockListJobs.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(
      <AlgorithmSeenProvider>
        <ShiftsManagementPage />
      </AlgorithmSeenProvider>
    );

    fireEvent.click(await screen.findByTestId("shifts-content"));

    expect(await screen.findByTestId("algorithm-run-review-returned-job-42")).toBeVisible();
  });
});
