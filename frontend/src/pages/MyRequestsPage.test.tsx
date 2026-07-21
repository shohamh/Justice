import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import MyRequestsPage from "./MyRequestsPage";
import * as constraintsApi from "../api/constraints";
import * as exemptionsApi from "../api/exemptions";
import * as dutyConfigApi from "../api/dutyConfig";
import { useAuth } from "../auth/AuthContext";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../api/constraints");
vi.mock("../api/exemptions");
vi.mock("../api/dutyConfig");
vi.mock("../auth/AuthContext");
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const constraint = {
  id: "c1",
  soldier_id: "sol-1",
  start_date: "2026-01-01",
  end_date: "2026-01-05",
  reason: "x",
  status: "pending",
  decided_by: null,
  decided_at: null,
  decision_note: null,
  created_at: "2026-01-01",
} as constraintsApi.PersonalConstraint;

const exemptionRequest = {
  id: "er1",
  soldier_id: "sol-1",
  soldier_name: "A",
  node_name: null,
  exemption_type_id: "et-1",
  start_date: "2026-01-01",
  end_date: "2026-01-10",
  reason: "y",
  status: "pending_commander",
  enrollment_request_id: null,
  decided_by: null,
  decision_note: null,
  created_at: "2026-01-01T00:00:00Z",
  files: [],
} as unknown as exemptionsApi.ExemptionRequest;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useAuth).mockReturnValue({
    user: { id: "sol-1", full_name: "A", role: "soldier" },
  } as ReturnType<typeof useAuth>);
  vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([constraint]);
  vi.mocked(constraintsApi.getRemainingConstraintDays).mockResolvedValue({
    cap_days: 15,
    used_days: 5,
    remaining_days: 10,
    period_start: "2026-01-01",
    period_end: "2026-03-31",
  });
  vi.mocked(exemptionsApi.listMyExemptionRequests).mockResolvedValue([exemptionRequest]);
  vi.mocked(exemptionsApi.listExemptions).mockResolvedValue([]);
  vi.mocked(dutyConfigApi.listExemptionTypes).mockResolvedValue([]);
  vi.mocked(dutyConfigApi.getAllExemptionDutyTypeMaps).mockResolvedValue({});
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([]);
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MyRequestsPage />
    </QueryClientProvider>
  );
}

describe("MyRequestsPage - day-count badges", () => {
  it("shows a day-count badge next to a pending constraint row", async () => {
    renderPage();
    const row = await screen.findByTestId("constraint-row-c1");
    expect(within(row).getByText("(5 ימים)")).toBeTruthy();
  });

  it("shows a day-count badge next to an exemption-request row", async () => {
    renderPage();
    await screen.findByText("y");
    expect(screen.getByText("(10 ימים)")).toBeTruthy();
  });

  it("shows the remaining constraint days summary", async () => {
    renderPage();
    await screen.findByTestId("constraints-remaining");
    expect(constraintsApi.getRemainingConstraintDays).toHaveBeenCalled();
  });
});
