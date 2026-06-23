import { render, screen, waitFor } from "@testing-library/react";
import ShiftsManagementPage from "./ShiftsManagementPage";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../ShiftsPage", () => ({
  ShiftsContent: () => <div data-testid="shifts-content" />,
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
}));

function job(status: string, mode: string) {
  return { status, mode };
}

describe("ShiftsManagementPage — algorithm run badges", () => {
  beforeEach(() => {
    mockListJobs.mockReset();
  });

  test("renders no badges when there are no jobs", async () => {
    mockListJobs.mockResolvedValue({ items: [], total: 0 });
    render(<ShiftsManagementPage />);
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
    render(<ShiftsManagementPage />);

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
    render(<ShiftsManagementPage />);

    expect(await screen.findByTestId("algo-badge-running")).toHaveTextContent("1");
    expect(screen.queryByTestId("algo-badge-draft")).not.toBeInTheDocument();
    expect(screen.queryByTestId("algo-badge-done")).not.toBeInTheDocument();
    expect(screen.queryByTestId("algo-badge-failed")).not.toBeInTheDocument();
  });
});
