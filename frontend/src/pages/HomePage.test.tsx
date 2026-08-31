import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";

import HomePage from "./HomePage";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";
import * as assignmentsApi from "../api/assignments";
import * as dutyConfigApi from "../api/dutyConfig";
import * as swapsApi from "../api/swaps";
import * as enrollmentApi from "../api/enrollment";
import * as systemSettingsApi from "../api/systemSettings";
import * as scoringApi from "../api/scoring";
import * as constraintsApi from "../api/constraints";
import * as exemptionsApi from "../api/exemptions";
import * as soldiersApi from "../api/soldiers";
import * as rangesApi from "../api/ranges";
import * as hierarchyTransfersApi from "../api/hierarchyTransfers";
import * as publicSettingsApi from "../api/publicSettings";
import type { PermissionUser } from "../auth/permissions";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      (options?.defaultValue as string | undefined) ?? key,
  }),
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("../api/assignments");
vi.mock("../api/dutyConfig");
vi.mock("../api/swaps");
vi.mock("../api/enrollment");
vi.mock("../api/systemSettings");
vi.mock("../api/scoring");
vi.mock("../api/constraints");
vi.mock("../api/exemptions");
vi.mock("../api/soldiers");
vi.mock("../api/ranges");
vi.mock("../api/hierarchyTransfers");
vi.mock("../api/publicSettings");
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const mockUser: PermissionUser = {
  id: "soldier-1",
  full_name: "חייל בדיקה",
  role: "soldier",
  hierarchy_node_id: null,
  is_commander: false,
  is_duty_manager: false,
};

vi.mock("../components/UnitCalendar", () => ({
  default: () => <div data-testid="unit-calendar" />,
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: mockUser }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(mockUser, {
    id: "soldier-1",
    full_name: "חייל בדיקה",
    role: "soldier",
    hierarchy_node_id: null,
    is_commander: false,
    is_duty_manager: false,
  });
  vi.mocked(assignmentsApi.listEffectiveDuties).mockResolvedValue([]);
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([]);
  vi.mocked(dutyConfigApi.listLocations).mockResolvedValue([]);
  vi.mocked(swapsApi.listMySwaps).mockResolvedValue([]);
  vi.mocked(swapsApi.listPendingSwaps).mockResolvedValue([]);
  vi.mocked(enrollmentApi.listPendingEnrollments).mockResolvedValue([]);
  vi.mocked(systemSettingsApi.getSystemSettings).mockResolvedValue({});
  vi.mocked(scoringApi.getTransparency).mockResolvedValue({ rows: [], can_see_exemption_aggregates: false });
  vi.mocked(scoringApi.getBreakdown).mockResolvedValue({ per_type: [], adjustments: [] });
  vi.mocked(scoringApi.getBurdenShare).mockResolvedValue({
    has_group: false, burden_share: null, rank: null, group_size: null,
    duty_type_names: [], peer_scores: [], mean: null, stddev: null, cv: null, low_sample: false,
  });
  vi.mocked(scoringApi.getBurdenShareBreakdown).mockResolvedValue({ quarters: [], burden_share: "0", A_i: "0", W_i: "0" });
  vi.mocked(constraintsApi.getPendingCount).mockResolvedValue(0);
  vi.mocked(exemptionsApi.getPendingExemptionCount).mockResolvedValue(0);
  vi.mocked(soldiersApi.getPendingFieldUpdateCount).mockResolvedValue(0);
  vi.mocked(rangesApi.getRanges).mockResolvedValue([]);
  vi.mocked(hierarchyTransfersApi.listPendingTransferRequests).mockResolvedValue([]);
  vi.mocked(publicSettingsApi.getPublicSettings).mockResolvedValue({});
});

function renderHome() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SoldierModalProvider>
          <HomePage />
        </SoldierModalProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HomePage - required scoring data load errors", () => {
  it("shows a load error banner when the transparency response is malformed", async () => {
    vi.mocked(scoringApi.getTransparency).mockRejectedValue(new Error("Invalid transparency response"));
    renderHome();

    expect(await screen.findByText("home.score_load_error")).toHaveAttribute("role", "alert");
  });

  it("shows a load error banner when the score breakdown response is malformed", async () => {
    vi.mocked(scoringApi.getBreakdown).mockRejectedValue(new Error("Invalid score breakdown response"));
    renderHome();

    expect(await screen.findByText("home.score_load_error")).toHaveAttribute("role", "alert");
  });

  it("renders no scoring load-error banner when every scoring query succeeds", async () => {
    renderHome();

    await screen.findByText("home.welcome");
    expect(screen.queryByText("home.score_load_error")).not.toBeInTheDocument();
  });

  it("shows the command section with a visible scope label before the personal calendar for management users", async () => {
    Object.assign(mockUser, {
      role: "commander",
      hierarchy_node_id: "node-1",
      is_commander: true,
    });

    renderHome();

    const commandSection = await screen.findByRole("region", { name: "ניהול היחידה" });
    expect(screen.getByText("היחידה / תת-העץ שבאחריותך")).toBeInTheDocument();

    const calendar = screen.getByTestId("unit-calendar");
    const position = commandSection.compareDocumentPosition(calendar);
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
