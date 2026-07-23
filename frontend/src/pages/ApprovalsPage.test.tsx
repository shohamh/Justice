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
import * as hierarchyTransfersApi from "../api/hierarchyTransfers";
import { api } from "../api/client";
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
vi.mock("../api/hierarchyTransfers");
vi.mock("../api/client", () => ({
  api: { get: vi.fn() },
}));
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const swap = {
  id: "s1",
  duty_assignment_id: "da1",
  duty_date: "2026-01-05",
  requesting_soldier_id: "sol-2",
  target_soldier_id: null,
  covering_soldier_id: "sol-3",
  status: "pending_approval",
  reason: null,
  requester_side_approved: false,
  covering_side_approved: false,
  decision_note: null,
  offered_assignment_ids: [],
  created_at: "2026-01-01",
  duty_type_name: null,
  duty_location_name: null,
  duty_type_id: null,
  duty_location_id: null,
  duty_start_date: null,
  duty_end_date: null,
  duty_shift_id: null,
  requesting_soldier_name: "B",
  covering_soldier_name: "C",
  requester_manager_approvals: [],
  covering_manager_approvals: [],
} as swapsApi.SwapRequest;

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

const exemptionRequestWithFile = {
  id: "er1",
  soldier_id: "sol-4",
  soldier_name: "D",
  node_name: null,
  exemption_type_id: "et1",
  start_date: "2026-01-01",
  end_date: null,
  reason: "x",
  status: "pending_commander",
  enrollment_request_id: null,
  decided_by: null,
  decision_note: null,
  created_at: "2026-01-01",
  files: [
    { id: "f1", file_name: "note.pdf", content_type: "application/pdf", created_at: "2026-01-01" },
  ],
} as exemptionsApi.ExemptionRequest;

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
  vi.mocked(hierarchyTransfersApi.listPendingTransferRequests).mockResolvedValue([]);
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
      expect(screen.getByText("הבקשה כבר טופלה")).toBeInTheDocument();
    });
  });

  it("shows the translated cover_blocked message when approving a swap fails", async () => {
    vi.mocked(swapsApi.listPendingSwaps).mockResolvedValue([swap]);
    vi.mocked(swapsApi.approveSwapSide).mockRejectedValue({
      response: { data: { detail: "cover_blocked:overlap" } },
    });
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
    const swapsTab = await screen.findByTestId("approvals-tab-swaps");
    fireEvent.click(swapsTab);
    const approveBtn = await screen.findByText("approvals.approve (swaps.requester)");
    fireEvent.click(approveBtn);
    await waitFor(() => {
      expect(screen.getByText("קיימת חפיפה עם תורנות אחרת")).toBeInTheDocument();
    });
  });
});

describe("ApprovalsPage - transfers tab", () => {
  it("shows pending transfer requests with approve/reject actions", async () => {
    vi.mocked(hierarchyTransfersApi.listPendingTransferRequests).mockResolvedValue([
      { id: "tr1", soldier_id: "sol-9", from_node_id: "n1", to_node_id: "n2", status: "pending" },
    ]);
    vi.mocked(hierarchyTransfersApi.approveTransferRequest).mockResolvedValue(
      { id: "tr1", soldier_id: "sol-9", from_node_id: "n1", to_node_id: "n2", status: "approved" },
    );

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

    const transfersTab = await screen.findByTestId("approvals-tab-transfers");
    fireEvent.click(transfersTab);

    const approveBtn = await screen.findByTestId("transfer-approve-tr1");
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(hierarchyTransfersApi.approveTransferRequest).toHaveBeenCalledWith("tr1");
    });
  });

  it("rejects a pending transfer request with a decision note", async () => {
    vi.mocked(hierarchyTransfersApi.listPendingTransferRequests).mockResolvedValue([
      { id: "tr1", soldier_id: "sol-9", from_node_id: "n1", to_node_id: "n2", status: "pending" },
    ]);
    vi.mocked(hierarchyTransfersApi.rejectTransferRequest).mockResolvedValue(
      { id: "tr1", soldier_id: "sol-9", from_node_id: "n1", to_node_id: "n2", status: "rejected" },
    );

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

    const transfersTab = await screen.findByTestId("approvals-tab-transfers");
    fireEvent.click(transfersTab);

    const noteInput = await screen.findByTestId("transfer-reject-note-tr1");
    fireEvent.change(noteInput, { target: { value: "לא רלוונטי" } });
    const rejectBtn = screen.getByTestId("transfer-reject-tr1");
    fireEvent.click(rejectBtn);

    await waitFor(() => {
      expect(hierarchyTransfersApi.rejectTransferRequest).toHaveBeenCalledWith("tr1", "לא רלוונטי");
    });
  });
});

describe("ApprovalsPage - exemption file links", () => {
  it("opens exemption files via an authenticated blob fetch, not a raw href", async () => {
    vi.mocked(exemptionsApi.listPendingExemptionRequests).mockResolvedValue([exemptionRequestWithFile]);
    vi.mocked(exemptionsApi.exemptionFileDownloadUrl).mockReturnValue("/api/exemption-requests/er1/files/f1");
    const blob = new Blob(["data"], { type: "application/pdf" });
    vi.mocked(api.get).mockResolvedValue({ data: blob });

    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
    URL.revokeObjectURL = vi.fn();
    const openSpy = vi.spyOn(window, "open").mockReturnValue({ addEventListener: vi.fn() } as unknown as Window);

    try {
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
      const exemptionsTab = await screen.findByTestId("approvals-tab-exemptions");
      fireEvent.click(exemptionsTab);
      const fileLink = await screen.findByText(/note\.pdf/);
      expect(fileLink.tagName).toBe("BUTTON");
      fireEvent.click(fileLink);

      await waitFor(() => {
        expect(api.get).toHaveBeenCalledWith(
          "/api/exemption-requests/er1/files/f1",
          expect.objectContaining({ responseType: "blob" }),
        );
      });
      expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
      expect(openSpy).toHaveBeenCalledWith("blob:mock-url", "_blank");
    } finally {
      URL.createObjectURL = originalCreateObjectURL;
      URL.revokeObjectURL = originalRevokeObjectURL;
      openSpy.mockRestore();
    }
  });

  it("shows an error message when the exemption file fetch fails", async () => {
    vi.mocked(exemptionsApi.listPendingExemptionRequests).mockResolvedValue([exemptionRequestWithFile]);
    vi.mocked(exemptionsApi.exemptionFileDownloadUrl).mockReturnValue("/api/exemption-requests/er1/files/f1");
    vi.mocked(api.get).mockRejectedValue({
      response: { status: 404, data: { detail: "file_not_found" } },
    });

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
    const exemptionsTab = await screen.findByTestId("approvals-tab-exemptions");
    fireEvent.click(exemptionsTab);
    const fileLink = await screen.findByText(/note\.pdf/);
    fireEvent.click(fileLink);

    await waitFor(() => {
      expect(screen.getByText("הקובץ לא נמצא")).toBeInTheDocument();
    });
  });
});
