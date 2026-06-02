import { render, screen, fireEvent } from "@testing-library/react";
import ManageSheet from "./ManageSheet";

vi.mock("react-router-dom", () => ({
  Link: ({ to, children, onClick, ...props }: { to: string; children: React.ReactNode; onClick?: () => void; [key: string]: unknown }) => (
    <a href={to} onClick={onClick} {...props}>{children}</a>
  ),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

describe("ManageSheet", () => {
  test("renders nothing when closed", () => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
    render(<ManageSheet open={false} onClose={() => {}} />);
    expect(screen.queryByText("nav.section_personal")).not.toBeInTheDocument();
  });

  test("renders personal section for all roles when open", () => {
    mockUseAuth.mockReturnValue({ user: { role: "soldier" } });
    render(<ManageSheet open={true} onClose={() => {}} />);
    expect(screen.getByText("nav.section_personal")).toBeInTheDocument();
    expect(screen.getByText("nav.my_requests")).toBeInTheDocument();
    expect(screen.getByText("nav.swaps")).toBeInTheDocument();
    expect(screen.getByText("nav.transparency")).toBeInTheDocument();
  });

  test("renders team section for canManageTeam roles", () => {
    mockUseAuth.mockReturnValue({ user: { role: "commander" } });
    render(<ManageSheet open={true} onClose={() => {}} />);
    expect(screen.getByText("nav.section_team")).toBeInTheDocument();
    expect(screen.getByText("nav.team_hierarchy")).toBeInTheDocument();
    expect(screen.getByText("nav.unit_calendar")).toBeInTheDocument();
    expect(screen.getByText("nav.command_dashboard")).toBeInTheDocument();
  });

  test("does not render team section for soldier role", () => {
    mockUseAuth.mockReturnValue({ user: { role: "soldier" } });
    render(<ManageSheet open={true} onClose={() => {}} />);
    expect(screen.queryByText("nav.section_team")).not.toBeInTheDocument();
  });

  test("renders planning section for canManageDuties roles", () => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
    render(<ManageSheet open={true} onClose={() => {}} />);
    expect(screen.getByText("nav.section_planning")).toBeInTheDocument();
    expect(screen.getByText("nav.duty_config")).toBeInTheDocument();
    expect(screen.getByText("nav.shifts")).toBeInTheDocument();
  });

  test("calls onClose when backdrop is clicked", () => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
    const onClose = vi.fn();
    render(<ManageSheet open={true} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("manage-sheet-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test("calls onClose when a link is clicked", () => {
    mockUseAuth.mockReturnValue({ user: { role: "soldier" } });
    const onClose = vi.fn();
    render(<ManageSheet open={true} onClose={onClose} />);
    fireEvent.click(screen.getByText("nav.my_requests"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
