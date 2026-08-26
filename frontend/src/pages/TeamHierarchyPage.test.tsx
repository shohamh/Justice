import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import TeamHierarchyPage from "./TeamHierarchyPage";
import * as soldiersApi from "../api/soldiers";
import * as hierarchyApi from "../api/hierarchy";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("../api/soldiers");
vi.mock("../api/hierarchy");
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../components/HierarchyTree", () => ({
  default: () => <div data-testid="hierarchy-tree-stub" />,
}));
vi.mock("../components/TelegramBadge", () => ({
  default: () => <span data-testid="telegram-badge-stub" />,
}));
vi.mock("../contexts/SoldierModalContext", () => ({
  useSoldierModal: () => ({ openSoldierModal: vi.fn() }),
}));
vi.mock("../hooks/usePortfolioDialog", () => ({
  usePortfolioDialog: () => ({ open: vi.fn(), dialog: null }),
}));

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

const soldier = {
  id: "sol-1",
  personal_number: "1234567",
  full_name: "חייל בדיקה",
  role: "soldier",
  hierarchy_node_id: null,
  phone: null,
  must_change_password: false,
  left_at: null,
  enrolled_at: "2026-01-01",
  gender: null,
  is_officer: null,
  is_career: false,
  rank: null,
  rank_track: null,
  next_rank_date: null,
  next_rank_date_overridden: false,
  can_edit_rank_advancement: false,
  bahad1_graduate: false,
  has_military_driving_license: null,
  military_driving_license_expiry: null,
  enlistment_date: null,
  mandatory_end_date: null,
  discharge_date: null,
  last_mitvahim_date: null,
  last_alal_date: null,
  telegram_linked: false,
} as soldiersApi.SoldierDTO;

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TeamHierarchyPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hierarchyApi.fetchTree).mockResolvedValue([]);
  vi.mocked(soldiersApi.listSoldiers).mockResolvedValue([soldier]);
  window.confirm = vi.fn().mockReturnValue(true);
  window.alert = vi.fn();
});

describe("TeamHierarchyPage - remove button gating", () => {
  it("hides the remove button when can_delete_soldier is false", async () => {
    mockUseAuth.mockReturnValue({
      user: { id: "u1", role: "commander", is_commander: true, can_delete_soldier: false },
    });
    renderPage();
    await screen.findByText("חייל בדיקה");
    expect(screen.queryByTestId(`remove-${soldier.personal_number}`)).not.toBeInTheDocument();
  });

  it("shows the remove button when can_delete_soldier is true", async () => {
    mockUseAuth.mockReturnValue({
      user: { id: "u1", role: "commander", is_commander: true, can_delete_soldier: true },
    });
    renderPage();
    expect(await screen.findByTestId(`remove-${soldier.personal_number}`)).toBeInTheDocument();
  });

  it("shows a friendly error and does not refresh when delete is forbidden", async () => {
    mockUseAuth.mockReturnValue({
      user: { id: "u1", role: "commander", is_commander: true, can_delete_soldier: true },
    });
    vi.mocked(soldiersApi.softDeleteSoldier).mockRejectedValueOnce({
      response: { status: 403, data: { detail: "forbidden" } },
    });
    renderPage();
    const removeBtn = await screen.findByTestId(`remove-${soldier.personal_number}`);
    fireEvent.click(removeBtn);
    await waitFor(() => {
      expect(screen.getByText(/אין לך הרשאה/)).toBeInTheDocument();
    });
  });
});

describe("TeamHierarchyPage - admin promotion", () => {
  it("requires explicit confirmation and the acting admin password before promotion", async () => {
    mockUseAuth.mockReturnValue({
      user: { id: "u1", role: "admin", is_commander: false, can_delete_soldier: false },
    });
    renderPage();

    fireEvent.click(await screen.findByTestId(`promote-admin-${soldier.personal_number}`));
    expect(screen.getByTestId("promote-admin-modal")).toBeInTheDocument();
    vi.mocked(soldiersApi.promoteSoldierToAdmin).mockResolvedValueOnce({ ...soldier, role: "admin" });

    const confirm = screen.getByTestId("promote-admin-confirm") as HTMLButtonElement;
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("team.current_password"), { target: { value: "ActingAdmin!123" } });
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByTestId("promote-admin-acknowledgement"));
    expect(confirm).not.toBeDisabled();
    fireEvent.click(confirm);

    await waitFor(() => expect(soldiersApi.promoteSoldierToAdmin).toHaveBeenCalledWith(
      soldier.id, "ActingAdmin!123",
    ));
  });

  it("does not offer promotion to a non-admin actor", async () => {
    mockUseAuth.mockReturnValue({
      user: { id: "u1", role: "soldier", is_commander: true, can_delete_soldier: false },
    });
    renderPage();

    await screen.findByText("חייל בדיקה");
    expect(screen.queryByTestId(`promote-admin-${soldier.personal_number}`)).not.toBeInTheDocument();
  });
});
