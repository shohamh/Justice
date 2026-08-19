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

const mockUseAuth = vi.fn(() => ({ user: { id: "viewer-1", role: "admin" } }));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

const swap = {
  id: "s1",
  duty_assignment_id: "da1",
  duty_date: "2026-01-05",
  requesting_soldier_id: "sol-2",
  open_to_marketplace: false,
  status: "open",
  reason: null,
  requester_side_approved: false,
  decision_note: null,
  created_at: "2026-01-01",
  duty_type_name: null,
  duty_location_name: null,
  duty_type_id: null,
  duty_location_id: null,
  duty_start_date: null,
  duty_end_date: null,
  duty_shift_id: null,
  requesting_soldier_name: "B",
  requester_manager_approvals: [
    {
      commander_id: "m1",
      commander_name: null,
      approved: false,
      approved_by: null,
      approved_by_name: null,
      approved_at: null,
      rejected: false,
      rejected_by: null,
      rejected_by_name: null,
      rejected_at: null,
      approver_kind: "commander",
    },
  ],
  candidates: [],
} as swapsApi.SwapRequest;

function makeCandidate(overrides: Partial<swapsApi.SwapCandidate>): swapsApi.SwapCandidate {
  return {
    id: "cand-default",
    soldier_id: "sol-x",
    soldier_name: "X",
    source: "invited",
    status: "pending",
    soldier_side_approved: null,
    offered_assignment_ids: [],
    manager_approvals: [],
    ...overrides,
  };
}

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
  can_approve_commander_step: true,
  can_approve_duty_manager_step: true,
} as exemptionsApi.ExemptionRequest;

beforeEach(() => {
  vi.clearAllMocks();
  mockUseAuth.mockReturnValue({ user: { id: "viewer-1", role: "admin" } });
  vi.mocked(constraintsApi.listPendingApprovals).mockResolvedValue([constraint]);
  vi.mocked(constraintsApi.approveConstraint).mockRejectedValue({
    response: { status: 400, data: { detail: "already_decided" } },
  });
  vi.mocked(exemptionsApi.listPendingExemptionRequests).mockResolvedValue([]);
  vi.mocked(exemptionsApi.exemptionFileDownloadUrl).mockReturnValue("");
  vi.mocked(soldiersApi.listPendingFieldUpdates).mockResolvedValue([]);
  vi.mocked(swapsApi.listPendingSwaps).mockResolvedValue([]);
  vi.mocked(swapsApi.getSwapConfig).mockResolvedValue({
    require_manager_approval: true, require_duty_manager_approval: true, max_specific_targets: 5,
  });
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
    vi.mocked(swapsApi.managerApproveSwap).mockRejectedValue({
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
    const approveBtn = await screen.findByText("approvals.approve");
    fireEvent.click(approveBtn);
    await waitFor(() => {
      expect(screen.getByText("קיימת חפיפה עם תורנות אחרת")).toBeInTheDocument();
    });
  });
});

describe("ApprovalsPage - swaps tab duty-manager empty state", () => {
  it("shows the duty-manager empty-state text when the setting is on but no duty manager is scoped", async () => {
    // require_duty_manager_approval is already true in the shared beforeEach
    // mock. `swap` has only a commander row in requester_manager_approvals —
    // no duty_manager row — so with the setting-based (not presence-based)
    // showDutyManagerRow computation, the row should still render and show
    // the informative empty-state text rather than vanish entirely.
    vi.mocked(swapsApi.listPendingSwaps).mockResolvedValue([swap]);

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

    // react-i18next is mocked in this file to return raw keys (t = (k) => k),
    // so assert on the translation key rather than the rendered Hebrew string
    // (see DirectCommanderApproval.test.tsx for the real-string version).
    expect(await screen.findByText("swaps.no_duty_manager_assigned")).toBeInTheDocument();
  });
});

describe("ApprovalsPage - swaps tab per-candidate approvals", () => {
  it("shows one approval block per live candidate on a swap with multiple candidates", async () => {
    const pendingCandidate = makeCandidate({
      id: "cand-1",
      soldier_id: "sol-10",
      soldier_name: "Pending Candidate",
      status: "pending",
      manager_approvals: [],
    });
    const acceptedCandidate = makeCandidate({
      id: "cand-2",
      soldier_id: "sol-11",
      soldier_name: "Accepted Candidate",
      status: "accepted",
      manager_approvals: [
        {
          commander_id: "m2",
          commander_name: "Commander Two",
          approved: false,
          approved_by: null,
          approved_by_name: null,
          approved_at: null,
          rejected: false,
          rejected_by: null,
          rejected_by_name: null,
          rejected_at: null,
          approver_kind: "commander",
        },
      ],
    });
    // A declined candidate should NOT get its own block — only pending/accepted are "live".
    const declinedCandidate = makeCandidate({
      id: "cand-3",
      soldier_id: "sol-12",
      soldier_name: "Declined Candidate",
      status: "declined",
    });

    vi.mocked(swapsApi.listPendingSwaps).mockResolvedValue([
      { ...swap, candidates: [pendingCandidate, acceptedCandidate, declinedCandidate] },
    ]);

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

    // Each live candidate's name appears twice: once in the column-strip label
    // above, and once more in the restored per-candidate action-card header
    // (Finding 2) — that second occurrence is what prevents a mis-click
    // between action cards when there are 2+ live candidates.
    const pendingMatches = await screen.findAllByText("Pending Candidate");
    expect(pendingMatches.length).toBe(2);
    const acceptedMatches = screen.getAllByText("Accepted Candidate");
    expect(acceptedMatches.length).toBe(2);
    expect(screen.queryByText("Declined Candidate")).not.toBeInTheDocument();

    // Each live candidate gets its own independent reject button — clicking
    // the accepted candidate's reject must only reject that candidate, not the
    // whole request and not the other (pending) candidate.
    // Order: [0] whole-request reject, [1] cand-1 (pending), [2] cand-2 (accepted).
    const rejectButtons = screen.getAllByText("approvals.reject");
    expect(rejectButtons.length).toBe(3);

    fireEvent.click(rejectButtons[2]);
    await waitFor(() => {
      expect(swapsApi.managerRejectSwap).toHaveBeenCalledWith("s1", undefined, "cand-2");
    });
    expect(swapsApi.managerRejectSwap).toHaveBeenCalledTimes(1);

    // The accepted candidate's manager-approval button acts on that candidate only
    // (the requester side also has one approve button — theirs must not fire, only cand-2's).
    const approveButtons = screen.getAllByText("approvals.approve");
    expect(approveButtons.length).toBe(2);
    fireEvent.click(approveButtons[1]);
    await waitFor(() => {
      expect(swapsApi.managerApproveSwap).toHaveBeenCalledWith("s1", "covering", "cand-2");
    });
  });

  it("moves a swap the viewer has no authority on to the waiting tab instead of the swaps tab", async () => {
    mockUseAuth.mockReturnValue({ user: { id: "unrelated-viewer", role: "commander" } });
    const acceptedCandidate = makeCandidate({
      id: "cand-2",
      soldier_id: "sol-11",
      soldier_name: "Accepted Candidate",
      status: "accepted",
      manager_approvals: [
        {
          commander_id: "m2",
          commander_name: "Commander Two",
          approved: false,
          approved_by: null,
          approved_by_name: null,
          approved_at: null,
          rejected: false,
          rejected_by: null,
          rejected_by_name: null,
          rejected_at: null,
          approver_kind: "commander",
        },
      ],
    });
    vi.mocked(swapsApi.listPendingSwaps).mockResolvedValue([
      { ...swap, candidates: [acceptedCandidate] },
    ]);

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

    // A viewer who isn't a chain match on either the requester side (m1) or
    // this candidate's side (m2), and isn't a duty manager, has no action on
    // this swap at all — it belongs in the waiting tab, not the swaps tab.
    expect(screen.getByText("approvals.none")).toBeInTheDocument();
    expect(screen.queryByText("Accepted Candidate")).not.toBeInTheDocument();

    const waitingTab = await screen.findByTestId("approvals-tab-waiting");
    fireEvent.click(waitingTab);
    expect(await screen.findByText("swaps.requester: B")).toBeInTheDocument();
  });

  it("shows only the per-candidate reject for a commander authorized on the candidate's side only", async () => {
    mockUseAuth.mockReturnValue({ user: { id: "m2", role: "commander" } });
    const acceptedCandidate = makeCandidate({
      id: "cand-2",
      soldier_id: "sol-11",
      soldier_name: "Accepted Candidate",
      status: "accepted",
      manager_approvals: [
        {
          commander_id: "m2",
          commander_name: "Commander Two",
          approved: false,
          approved_by: null,
          approved_by_name: null,
          approved_at: null,
          rejected: false,
          rejected_by: null,
          rejected_by_name: null,
          rejected_at: null,
          approver_kind: "commander",
        },
      ],
    });
    vi.mocked(swapsApi.listPendingSwaps).mockResolvedValue([
      { ...swap, candidates: [acceptedCandidate] },
    ]);

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

    await screen.findAllByText("Accepted Candidate");
    // m2 is only in the candidate's own chain (not the requester's, m1) —
    // exactly one reject button (the candidate's) should render.
    expect(screen.getAllByText("approvals.reject").length).toBe(1);
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
  it("opens exemption files via an authenticated blob fetch and previews them in-app", async () => {
    vi.mocked(exemptionsApi.listPendingExemptionRequests).mockResolvedValue([exemptionRequestWithFile]);
    vi.mocked(exemptionsApi.exemptionFileDownloadUrl).mockReturnValue("/exemption-requests/er1/files/f1");
    const blob = new Blob(["data"], { type: "application/pdf" });
    vi.mocked(api.get).mockResolvedValue({ data: blob });

    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
    URL.revokeObjectURL = vi.fn();

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
          "/exemption-requests/er1/files/f1",
          expect.objectContaining({ responseType: "blob" }),
        );
      });
      expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
      const downloadLink = await screen.findByRole("link", { name: /הורדה/ });
      expect(downloadLink).toHaveAttribute("href", "blob:mock-url");
      expect(downloadLink).toHaveAttribute("download", "note.pdf");

      fireEvent.click(screen.getByRole("button", { name: "✕" }));
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
    } finally {
      URL.createObjectURL = originalCreateObjectURL;
      URL.revokeObjectURL = originalRevokeObjectURL;
    }
  });

  it("shows an error message when the exemption file fetch fails", async () => {
    vi.mocked(exemptionsApi.listPendingExemptionRequests).mockResolvedValue([exemptionRequestWithFile]);
    vi.mocked(exemptionsApi.exemptionFileDownloadUrl).mockReturnValue("/exemption-requests/er1/files/f1");
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

  it("shows a specific message when opening an exemption file returns no_permission", async () => {
    vi.mocked(exemptionsApi.listPendingExemptionRequests).mockResolvedValue([exemptionRequestWithFile]);
    vi.mocked(exemptionsApi.exemptionFileDownloadUrl).mockReturnValue("/exemption-requests/er1/files/f1");
    vi.mocked(api.get).mockRejectedValue({
      response: { status: 403, data: { detail: "no_permission" } },
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
      expect(screen.queryByText("שגיאה בביצוע הפעולה")).not.toBeInTheDocument();
      expect(screen.getByText("אין לך הרשאה לבצע פעולה זו")).toBeInTheDocument();
    });
  });
});

describe("ApprovalsPage - approve button authority", () => {
  it("moves a duty-manager exemption the viewer can't approve to the waiting tab instead of the exemptions tab", async () => {
    vi.mocked(exemptionsApi.listPendingExemptionRequests).mockResolvedValue([
      { ...exemptionRequestWithFile, status: "pending_duty_manager", can_approve_duty_manager_step: false },
    ]);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
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
    expect(screen.queryByTestId(`er-reject-note-${exemptionRequestWithFile.id}`)).not.toBeInTheDocument();
    expect(screen.queryByTestId(`er-approve-${exemptionRequestWithFile.id}`)).not.toBeInTheDocument();

    const waitingTab = await screen.findByTestId("approvals-tab-waiting");
    fireEvent.click(waitingTab);
    await screen.findByText("D");
  });

  it("moves a field update the viewer can't approve to the waiting tab instead of the field-updates tab", async () => {
    vi.mocked(soldiersApi.listPendingFieldUpdates).mockResolvedValue([
      {
        id: "fu1", soldier_id: "sol-5", soldier_name: "E", node_name: null, field_name: "discharge_date",
        previous_value: null, new_value: "2027-01-01", status: "pending", decided_by: null, decided_at: null,
        decision_note: null, created_at: "2026-01-01", nearest_commander: null, nearest_duty_manager: null,
        can_approve: false,
      } as soldiersApi.FieldUpdateDTO,
    ]);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SoldierModalProvider>
            <ApprovalsPage />
          </SoldierModalProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
    const fuTab = await screen.findByTestId("approvals-tab-field-updates");
    fireEvent.click(fuTab);
    expect(screen.queryByText("soldier_profile.discharge_date")).not.toBeInTheDocument();

    const waitingTab = await screen.findByTestId("approvals-tab-waiting");
    fireEvent.click(waitingTab);
    await screen.findByText("soldier_profile.discharge_date");
    expect(screen.queryByText("approvals.approve")).not.toBeInTheDocument();
  });
});

describe("ApprovalsPage - field update approver clarity", () => {
  it("hides the commander row for a field only a duty manager can ever decide, even when a nearest commander exists", async () => {
    vi.mocked(soldiersApi.listPendingFieldUpdates).mockResolvedValue([
      {
        id: "fu2", soldier_id: "sol-6", soldier_name: "F", node_name: null, field_name: "discharge_date",
        previous_value: null, new_value: "2027-01-01", status: "pending", decided_by: null, decided_at: null,
        decision_note: null, created_at: "2026-01-01",
        nearest_commander: { id: "cmd-1", name: "מפקד בדיקה" },
        nearest_duty_manager: { id: "dm-1", name: "אחראי בדיקה" },
        can_approve: true,
      } as soldiersApi.FieldUpdateDTO,
    ]);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SoldierModalProvider>
            <ApprovalsPage />
          </SoldierModalProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
    const fuTab = await screen.findByTestId("approvals-tab-field-updates");
    fireEvent.click(fuTab);
    await screen.findByText("אחראי בדיקה"); // guard: the item rendered

    // Only a duty manager can ever decide a non-license field update — the
    // commander row would falsely suggest they're a valid decider too.
    expect(screen.queryByText("swaps.approver_kind_commander", { exact: false })).not.toBeInTheDocument();
    expect(screen.queryByText("מפקד בדיקה")).not.toBeInTheDocument();
    expect(screen.getByText("swaps.approver_kind_duty_manager", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("אחראי בדיקה")).toBeInTheDocument();
    expect(screen.queryByText("approvals.field_update_either_approver_suffices", { exact: false })).not.toBeInTheDocument();
  });

  it("shows both rows plus an either-suffices note for military_driving_license, where either kind can decide", async () => {
    vi.mocked(soldiersApi.listPendingFieldUpdates).mockResolvedValue([
      {
        id: "fu3", soldier_id: "sol-7", soldier_name: "G", node_name: null, field_name: "military_driving_license",
        previous_value: null, new_value: JSON.stringify({ has_license: true, expiry_date: null }),
        status: "pending", decided_by: null, decided_at: null, decision_note: null, created_at: "2026-01-01",
        nearest_commander: { id: "cmd-2", name: "מפקד רישיון" },
        nearest_duty_manager: { id: "dm-2", name: "אחראי רישיון" },
        can_approve: true,
      } as soldiersApi.FieldUpdateDTO,
    ]);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SoldierModalProvider>
            <ApprovalsPage />
          </SoldierModalProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
    const fuTab = await screen.findByTestId("approvals-tab-field-updates");
    fireEvent.click(fuTab);
    await screen.findByText("מפקד רישיון");

    expect(screen.getByText("swaps.approver_kind_commander", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("swaps.approver_kind_duty_manager", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("אחראי רישיון")).toBeInTheDocument();
    expect(screen.getByText("approvals.field_update_either_approver_suffices", { exact: false })).toBeInTheDocument();
  });
});
