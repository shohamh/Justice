import { fireEvent, render, screen } from "@testing-library/react";
import HelpModal from "./HelpModal";

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("../api/scoring", () => ({
  getEffortBreakdown: vi.fn(() => Promise.resolve({ quarters: [], effort_score: "0", A_i: "0", W_i: "0" })),
}));

function setUser(role: "soldier" | "commander" | "duty_manager" | "admin", overrides: Partial<{ is_commander: boolean; is_duty_manager: boolean }> = {}) {
  mockUseAuth.mockReturnValue({
    user: { id: "u1", role, is_commander: false, is_duty_manager: false, ...overrides },
  });
}

describe("HelpModal tab visibility", () => {
  it("hides Approvals and Import tabs from a plain soldier", () => {
    setUser("soldier");
    render(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
    expect(screen.queryByText(/אישורים/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ייבוא/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "🔄 החלפות" })).toBeInTheDocument();
  });

  it("shows Approvals but not Import to a commander", () => {
    setUser("commander", { is_commander: true });
    render(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
    expect(screen.getByText(/אישורים/)).toBeInTheDocument();
    expect(screen.queryByText(/ייבוא/)).not.toBeInTheDocument();
  });

  it("shows Import to a duty manager", () => {
    setUser("duty_manager", { is_duty_manager: true });
    render(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
    expect(screen.getByText(/ייבוא/)).toBeInTheDocument();
  });

  it("shows every tab to admin", () => {
    setUser("admin");
    render(<HelpModal onClose={() => {}} gimelimEnabled />);
    expect(screen.getByText(/אישורים/)).toBeInTheDocument();
    expect(screen.getByText(/ייבוא/)).toBeInTheDocument();
    expect(screen.getByText(/גימלים/)).toBeInTheDocument();
  });
});

it("shows corrected gimelim reason-visibility copy and undocumented-behavior callouts", () => {
  setUser("admin");
  render(<HelpModal onClose={() => {}} gimelimEnabled initialTab="gimelim" />);
  expect(screen.getByText(/מנהל תורנויות או מפקד שבתחום אחריותם/)).toBeInTheDocument();
});

it("Approvals tab explains each approval type for a commander", () => {
  setUser("commander", { is_commander: true });
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="approvals" />);
  expect(screen.getByText(/בקשות החלפה/)).toBeInTheDocument();
  expect(screen.getByText(/בקשות פטור/)).toBeInTheDocument();
});

it("expands a swap step's detail on click and collapses on second click", () => {
  setUser("soldier");
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="swaps" />);
  const step = screen.getByText(/חייל מגיש בקשת החלפה/);
  expect(screen.queryByText(/הבקשה יכולה להיות פתוחה/)).not.toBeInTheDocument();
  fireEvent.click(step);
  expect(screen.getByText(/הבקשה יכולה להיות פתוחה/)).toBeInTheDocument();
  fireEvent.click(step);
  expect(screen.queryByText(/הבקשה יכולה להיות פתוחה/)).not.toBeInTheDocument();
});
