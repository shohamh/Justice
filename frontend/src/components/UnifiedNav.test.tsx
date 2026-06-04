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

vi.mock("./NavSheet", () => ({
  default: ({ open, testId }: { open: boolean; testId?: string }) =>
    open ? <div data-testid={testId ?? "nav-sheet-open"} /> : null,
}));

describe("UnifiedNav — soldier role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "soldier" } });
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
    mockUseAuth.mockReturnValue({ user: { role: "commander" } });
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
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
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
