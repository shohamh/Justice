import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import UnifiedNav from "./UnifiedNav";

vi.mock("react-router-dom", () => ({
  useLocation: () => ({ pathname: "/" }),
  Link: ({ to, children, className, ...props }: { to: string; children: React.ReactNode; className?: string; [key: string]: unknown }) => (
    <a href={to} className={className} {...props}>{children}</a>
  ),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("../api/constraints", () => ({
  getPendingCount: vi.fn(() => Promise.resolve(0)),
}));
vi.mock("../api/exemptions", () => ({
  getPendingExemptionCount: vi.fn(() => Promise.resolve(0)),
}));
vi.mock("../api/soldiers", () => ({
  getPendingFieldUpdateCount: vi.fn(() => Promise.resolve(0)),
}));
vi.mock("../api/swaps", () => ({
  getIncomingSwapCount: vi.fn(() => Promise.resolve(0)),
}));

const mockListJobs = vi.fn();
vi.mock("../api/algorithm", () => ({
  listJobs: (...args: unknown[]) => mockListJobs(...args),
}));

vi.mock("./NavSheet", () => ({
  default: ({ open, testId }: { open: boolean; testId?: string }) =>
    open ? <div data-testid={testId ?? "nav-sheet-open"} /> : null,
}));

const mockSeedSeenIds = vi.fn();
const mockUseSeenJobs = vi.fn(() => ({
  seenIds: new Set<string>(),
  seedSeenIds: mockSeedSeenIds,
  markJobSeen: vi.fn(),
  markAllSeen: vi.fn(),
}));
vi.mock("../contexts/AlgorithmSeenContext", () => ({
  useSeenJobs: (...args: unknown[]) => mockUseSeenJobs(...args),
}));

function job(status: string, mode: string, error_message: string | null = null, id = "job-1") {
  return {
    id,
    status,
    mode,
    error_message,
    seen: false,
    total_duties: 0,
    assigned_duties: 0,
    created_at: "",
    started_at: null,
    finished_at: null,
    planning_start: "2027-01-01",
    planning_end: "2027-01-07",
    shift_count: 0,
  };
}

beforeEach(() => {
  mockListJobs.mockReset();
  mockListJobs.mockResolvedValue({ items: [], total: 0 });
  mockSeedSeenIds.mockReset();
  mockUseSeenJobs.mockReset();
  mockUseSeenJobs.mockImplementation(() => ({
    seenIds: new Set<string>(),
    seedSeenIds: mockSeedSeenIds,
    markJobSeen: vi.fn(),
    markAllSeen: vi.fn(),
  }));
});

describe("UnifiedNav — soldier role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "soldier", is_commander: false, is_duty_manager: false } });
  });

  test("renders 5 base tabs: my-requests, swaps, home, unit-calendar, transparency", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-my-requests").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-swaps").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-home").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-unit-calendar").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-transparency").length).toBeGreaterThan(0);
  });

  test("does not render commander or planning tabs", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("nav-commander")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-planning")).not.toBeInTheDocument();
  });

  test("does not render profile tab (profile is in header now)", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("nav-profile")).not.toBeInTheDocument();
  });
});

describe("UnifiedNav — commander role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "commander", is_commander: true, is_duty_manager: false } });
  });

  test("renders base tabs plus commander tab", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-home").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-commander").length).toBeGreaterThan(0);
  });

  test("does not render planning tab", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("nav-planning")).not.toBeInTheDocument();
  });

  test("commander button opens commander sheet", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("commander-sheet")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByTestId("nav-commander")[0]);
    expect(screen.getByTestId("commander-sheet")).toBeInTheDocument();
  });

  test("shows pending badge on commander tab when approvals pending", async () => {
    const { getPendingCount } = await import("../api/constraints");
    vi.mocked(getPendingCount).mockResolvedValueOnce(3);
    render(<UnifiedNav />);
    await waitFor(() => {
      expect(screen.getAllByTestId("pending-badge").length).toBeGreaterThan(0);
    });
  });
});

describe("UnifiedNav — duty_manager role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager", is_commander: false, is_duty_manager: true } });
  });

  test("renders base tabs plus commander and planning tabs", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-commander").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-planning").length).toBeGreaterThan(0);
  });

  test("planning button opens planning sheet", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("planning-sheet")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByTestId("nav-planning")[0]);
    expect(screen.getByTestId("planning-sheet")).toBeInTheDocument();
  });
});

describe("UnifiedNav — admin role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "admin" } });
  });

  test("renders base tabs plus commander and planning tabs", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-commander").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-planning").length).toBeGreaterThan(0);
  });
});

describe("UnifiedNav — algorithm badge color", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager", is_commander: false, is_duty_manager: true } });
  });

  test("shows red when any job failed, even with other statuses present", async () => {
    mockListJobs.mockResolvedValue({
      items: [job("running", "shadow"), job("failed", "dm_reviewed", "solver_timeout")],
      total: 2,
    });
    render(<UnifiedNav />);
    const badge = await screen.findAllByTestId("pending-badge");
    expect(badge.some((el) => el.className.includes("bg-red-500"))).toBe(true);
  });

  test("shows blue when running but nothing failed", async () => {
    mockListJobs.mockResolvedValue({
      items: [job("pending", "shadow"), job("done", "dm_reviewed")],
      total: 2,
    });
    render(<UnifiedNav />);
    const badge = await screen.findAllByTestId("pending-badge");
    expect(badge.some((el) => el.className.includes("bg-blue-500"))).toBe(true);
  });

  test("shows yellow when only drafts are pending review", async () => {
    mockListJobs.mockResolvedValue({
      items: [job("done", "shadow")],
      total: 1,
    });
    render(<UnifiedNav />);
    const badge = await screen.findAllByTestId("pending-badge");
    expect(badge.some((el) => el.className.includes("bg-yellow-500"))).toBe(true);
  });

  test("excludes cancelled jobs from the badge count", async () => {
    mockListJobs.mockResolvedValue({
      items: [job("failed", "shadow", "cancelled_by_user")],
      total: 1,
    });
    render(<UnifiedNav />);
    await waitFor(() => expect(mockListJobs).toHaveBeenCalled());
    expect(screen.queryByTestId("pending-badge")).not.toBeInTheDocument();
  });

  test("excludes a seen done job from the badge count", async () => {
    // Override the context mock to return a non-empty seenIds for this test
    mockUseSeenJobs.mockImplementation(() => ({
      seenIds: new Set(["job-seen"]),
      seedSeenIds: vi.fn(),
      markJobSeen: vi.fn(),
      markAllSeen: vi.fn(),
    }));
    mockListJobs.mockResolvedValue({
      items: [job("done", "shadow", null, "job-seen")],
      total: 1,
    });
    render(<UnifiedNav />);
    await waitFor(() => expect(mockListJobs).toHaveBeenCalled());
    expect(screen.queryByTestId("pending-badge")).not.toBeInTheDocument();
  });
});

describe("UnifiedNav — dual-role soldier (commander label, also a duty manager)", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({
      user: { role: "commander", is_commander: true, is_duty_manager: true },
    });
  });

  test("renders both commander and planning tabs", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-commander").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-planning").length).toBeGreaterThan(0);
  });
});
