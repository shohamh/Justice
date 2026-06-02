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

vi.mock("./ManageSheet", () => ({
  default: ({ open }: { open: boolean }) =>
    open ? <div data-testid="manage-sheet-open" /> : null,
}));

describe("UnifiedNav — soldier role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "soldier" } });
  });

  test("renders Home, My Duties, Requests, Swaps, Profile tabs", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-home").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-my-duties").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-my-requests").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-swaps").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-profile").length).toBeGreaterThan(0);
  });

  test("does not render Approvals or Manage tabs", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("nav-approvals")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-manage")).not.toBeInTheDocument();
  });
});

describe("UnifiedNav — manager role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
  });

  test("renders Home, My Duties, Approvals, Manage, Profile tabs", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-home").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-my-duties").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-approvals").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-manage").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-profile").length).toBeGreaterThan(0);
  });

  test("shows approval badge when pending count > 0", async () => {
    const { getPendingCount } = await import("../api/constraints");
    vi.mocked(getPendingCount).mockResolvedValueOnce(3);
    render(<UnifiedNav />);
    await waitFor(() => {
      expect(screen.getByTestId("pending-badge")).toBeInTheDocument();
    });
  });

  test("Manage button opens ManageSheet", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("manage-sheet-open")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByTestId("nav-manage")[0]);
    expect(screen.getByTestId("manage-sheet-open")).toBeInTheDocument();
  });
});
