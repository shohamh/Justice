import { render as testingLibraryRender, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import UnifiedNav, { aggregateBadgeCounts } from "./UnifiedNav";

function render(ui: React.ReactElement) {
  return testingLibraryRender(
    <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>,
  );
}

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

const mockUsePublicSettings = vi.fn(() => ({} as Record<string, unknown> | null));
vi.mock("../hooks/usePublicSettings", () => ({
  usePublicSettings: () => mockUsePublicSettings(),
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
const mockGetIneligibleSoldierCount = vi.fn();
vi.mock("../api/ineligibleSoldiers", () => ({
  getIneligibleSoldierCount: (...args: unknown[]) => mockGetIneligibleSoldierCount(...args),
}));

const mockListJobs = vi.fn();
vi.mock("../api/algorithm", () => ({
  listJobs: (...args: unknown[]) => mockListJobs(...args),
}));

vi.mock("./NavSheet", () => ({
  default: ({ open, testId, items }: { open: boolean; testId?: string; items?: { testId?: string; to?: string; badge?: number; badgeColor?: string }[] }) =>
    open ? (
      <div data-testid={testId ?? "nav-sheet-open"}>
        {items?.map((item) => (
          <a key={item.testId} data-testid={item.testId} href={item.to}>
            {item.badge != null && item.badge > 0 && (
              <span data-testid={item.testId === "nav-ranges" ? "ineligible-ranges-badge" : `${item.testId}-badge`} className={`bg-${item.badgeColor ?? "red"}-500`}>
                {item.badge}
              </span>
            )}
          </a>
        ))}
      </div>
    ) : null,
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
  mockGetIneligibleSoldierCount.mockReset();
  mockGetIneligibleSoldierCount.mockResolvedValue({ count: 0 });
  mockListJobs.mockReset();
  mockListJobs.mockResolvedValue({ items: [], total: 0 });
  mockUsePublicSettings.mockReset();
  mockUsePublicSettings.mockReturnValue({});
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

describe("UnifiedNav — standalone weapon-ineligible destination", () => {
  test.each([
    ["admin", { role: "admin" }],
    ["commander", { role: "commander", is_commander: true, is_duty_manager: false }],
    ["duty manager", { role: "duty_manager", is_commander: false, is_duty_manager: true }],
    ["ordinary user", { role: "soldier", is_commander: false, is_duty_manager: false }],
  ])("is absent for %s", (_, user) => {
    mockUseAuth.mockReturnValue({ user });
    render(<UnifiedNav />);
    expect(screen.queryByTestId("nav-weapon-ineligible")).not.toBeInTheDocument();
  });
});

describe("UnifiedNav — forced-callup (hakpaza) gating", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "commander", is_commander: true, is_duty_manager: false } });
  });

  test("shows hakpaza item in commander sheet when forced_callup.enabled is not false", () => {
    mockUsePublicSettings.mockReturnValue({ "forced_callup.enabled": true });
    render(<UnifiedNav />);
    fireEvent.click(screen.getAllByTestId("nav-commander")[0]);
    expect(screen.getByTestId("nav-hakpaza")).toBeInTheDocument();
  });

  test("hides hakpaza item in commander sheet when forced_callup.enabled is false", () => {
    mockUsePublicSettings.mockReturnValue({ "forced_callup.enabled": false });
    render(<UnifiedNav />);
    fireEvent.click(screen.getAllByTestId("nav-commander")[0]);
    expect(screen.queryByTestId("nav-hakpaza")).not.toBeInTheDocument();
  });
});

describe("UnifiedNav — ranges (mitvachim) gating", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager", is_commander: false, is_duty_manager: true } });
  });

  test("shows ranges item in planning sheet when mitvachim.enabled is true", () => {
    mockUsePublicSettings.mockReturnValue({ "mitvachim.enabled": true });
    render(<UnifiedNav />);
    fireEvent.click(screen.getAllByTestId("nav-planning")[0]);
    expect(screen.getByTestId("nav-ranges")).toBeInTheDocument();
    expect(screen.getByTestId("nav-ranges")).toHaveAttribute("href", "/ranges");
    expect(screen.queryByTestId("nav-weapon-ineligible")).not.toBeInTheDocument();
  });

  test("hides ranges item in planning sheet when mitvachim.enabled is false", () => {
    mockUsePublicSettings.mockReturnValue({ "mitvachim.enabled": false });
    render(<UnifiedNav />);
    fireEvent.click(screen.getAllByTestId("nav-planning")[0]);
    expect(screen.queryByTestId("nav-ranges")).not.toBeInTheDocument();
  });

  test("shows a red ineligible count badge on ranges for a duty manager", async () => {
    mockUsePublicSettings.mockReturnValue({ "mitvachim.enabled": true });
    mockGetIneligibleSoldierCount.mockResolvedValue({ count: 3 });
    render(<UnifiedNav />);
    fireEvent.click(screen.getAllByTestId("nav-planning")[0]);

    const badge = await screen.findByTestId("ineligible-ranges-badge");
    expect(badge).toHaveTextContent("3");
    expect(badge).toHaveClass("bg-red-500");
  });

  test("shows the ineligible count badge for an admin", async () => {
    mockUseAuth.mockReturnValue({ user: { role: "admin" } });
    mockUsePublicSettings.mockReturnValue({ "mitvachim.enabled": true });
    mockGetIneligibleSoldierCount.mockResolvedValue({ count: 2 });
    render(<UnifiedNav />);
    fireEvent.click(screen.getAllByTestId("nav-planning")[0]);

    expect(await screen.findByTestId("ineligible-ranges-badge")).toHaveTextContent("2");
  });

  test("hides the ineligible count badge when the count is zero", async () => {
    mockUsePublicSettings.mockReturnValue({ "mitvachim.enabled": true });
    mockGetIneligibleSoldierCount.mockResolvedValue({ count: 0 });
    render(<UnifiedNav />);
    fireEvent.click(screen.getAllByTestId("nav-planning")[0]);

    await waitFor(() => expect(mockGetIneligibleSoldierCount).toHaveBeenCalled());
    expect(screen.queryByTestId("ineligible-ranges-badge")).not.toBeInTheDocument();
  });

  test("does not fetch or show the badge when mitvachim is disabled", async () => {
    mockUsePublicSettings.mockReturnValue({ "mitvachim.enabled": false });
    mockGetIneligibleSoldierCount.mockResolvedValue({ count: 4 });
    render(<UnifiedNav />);
    fireEvent.click(screen.getAllByTestId("nav-planning")[0]);

    expect(screen.queryByTestId("nav-ranges")).not.toBeInTheDocument();
    expect(mockGetIneligibleSoldierCount).not.toHaveBeenCalled();
  });

  test("aggregates the ranges child count into the planning parent", async () => {
    mockUsePublicSettings.mockReturnValue({ "mitvachim.enabled": true });
    mockGetIneligibleSoldierCount.mockResolvedValue({ count: 3 });
    mockListJobs.mockResolvedValue({ items: [job("failed", "shadow", "solver_timeout")], total: 1 });
    render(<UnifiedNav />);
    fireEvent.click(screen.getAllByTestId("nav-planning")[0]);

    const parentBadge = await waitFor(() => {
      const badge = screen.getAllByTestId("pending-badge").find((element) => element.textContent === "4");
      expect(badge).toBeDefined();
      return badge;
    });
    expect(parentBadge).toHaveClass("bg-red-500");
  });

  test("hides the parent badge when child counts are zero", async () => {
    mockUsePublicSettings.mockReturnValue({ "mitvachim.enabled": true });
    mockGetIneligibleSoldierCount.mockResolvedValue({ count: 0 });
    render(<UnifiedNav />);
    fireEvent.click(screen.getAllByTestId("nav-planning")[0]);

    await waitFor(() => expect(mockGetIneligibleSoldierCount).toHaveBeenCalled());
    expect(screen.queryByTestId("pending-badge")).not.toBeInTheDocument();
  });

  test.each([
    ["loading", () => new Promise<{ count: number }>(() => {})],
    ["errored", () => Promise.reject(new Error("count unavailable"))],
  ])("hides the parent badge while the ranges count is %s", (_, countQuery) => {
    mockUsePublicSettings.mockReturnValue({ "mitvachim.enabled": true });
    mockGetIneligibleSoldierCount.mockImplementationOnce(countQuery);
    render(<UnifiedNav />);
    fireEvent.click(screen.getAllByTestId("nav-planning")[0]);

    expect(screen.queryByTestId("pending-badge")).not.toBeInTheDocument();
  });
});

describe("UnifiedNav — badge aggregation", () => {
  test("sums child counts and selects the worst color red > orange > blue > green", () => {
    expect(aggregateBadgeCounts([
      { badge: 2, badgeColor: "green" },
      { badge: 3, badgeColor: "yellow" },
      { badge: 4, badgeColor: "blue" },
      { badge: 5, badgeColor: "red" },
    ])).toEqual({ badge: 14, badgeColor: "red" });
    expect(aggregateBadgeCounts([{ badge: 2, badgeColor: "yellow" }, { badge: 1, badgeColor: "blue" }])).toEqual({ badge: 3, badgeColor: "yellow" });
    expect(aggregateBadgeCounts([{ badge: 0, badgeColor: "red" }, { badge: undefined, badgeColor: "green" }])).toEqual({ badge: 0, badgeColor: "green" });
  });
});
