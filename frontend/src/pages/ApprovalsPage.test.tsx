import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ApprovalsPage from "./ApprovalsPage";
import * as constraintsApi from "../api/constraints";
import * as exemptionsApi from "../api/exemptions";
import * as soldiersApi from "../api/soldiers";
import * as swapsApi from "../api/swaps";
import * as enrollmentApi from "../api/enrollment";
import * as hierarchyApi from "../api/hierarchy";
import * as authApi from "../api/auth";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("../api/constraints");
vi.mock("../api/exemptions");
vi.mock("../api/soldiers");
vi.mock("../api/swaps");
vi.mock("../api/enrollment");
vi.mock("../api/hierarchy");
vi.mock("../api/auth");
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const constraint = {
  id: "c1",
  soldier_id: "sol-1",
  soldier_name: "A",
  node_name: null,
  start_date: "2026-01-01",
  end_date: "2026-01-02",
  reason: "x",
  status: "pending",
  decided_by: null,
  decided_at: null,
  decision_note: null,
  created_at: "2026-01-01",
} as constraintsApi.PersonalConstraint;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(constraintsApi.listPendingApprovals).mockResolvedValue([constraint]);
  vi.mocked(constraintsApi.approveConstraint).mockRejectedValue({
    response: { status: 400, data: { detail: "already_decided" } },
  });
  vi.mocked(exemptionsApi.listPendingExemptionRequests).mockResolvedValue([]);
  vi.mocked(exemptionsApi.exemptionFileDownloadUrl).mockReturnValue("");
  vi.mocked(soldiersApi.listPendingFieldUpdates).mockResolvedValue([]);
  vi.mocked(swapsApi.listPendingSwaps).mockResolvedValue([]);
  vi.mocked(enrollmentApi.listPendingEnrollments).mockResolvedValue([]);
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
  vi.mocked(authApi.listPublicExemptionTypes).mockResolvedValue([]);
});

describe("ApprovalsPage - action error banner", () => {
  it("shows the backend error message when approving a constraint fails", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SoldierModalProvider>
            <ApprovalsPage />
          </SoldierModalProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
    const approveBtn = await screen.findByTestId("approve-c1");
    fireEvent.click(approveBtn);
    await waitFor(() => {
      expect(screen.getByText(/already_decided/)).toBeInTheDocument();
    });
  });
});
