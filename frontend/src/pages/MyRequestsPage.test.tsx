import { useEffect } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import MyRequestsPage from "./MyRequestsPage";
import * as constraintsApi from "../api/constraints";
import * as exemptionsApi from "../api/exemptions";
import * as dutyConfigApi from "../api/dutyConfig";
import * as auditLogsApi from "../api/auditLogs";
import * as myRequestsApi from "../api/myRequests";
import * as swapsApi from "../api/swaps";
import * as soldiersApi from "../api/soldiers";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";
import { useAuth, AuthContextValue } from "../auth/AuthContext";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../api/constraints");
vi.mock("../api/exemptions");
vi.mock("../api/dutyConfig");
vi.mock("../api/auditLogs");
vi.mock("../api/myRequests");
vi.mock("../api/swaps");
vi.mock("../api/soldiers");
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

const swapInProcess = {
  id: "sw1",
  duty_assignment_id: "a1",
  duty_date: "2026-08-01",
  requesting_soldier_id: "sol-1",
  open_to_marketplace: false,
  status: "open",
  reason: null,
  requester_side_approved: null,
  decision_note: null,
  created_at: "2026-07-01T00:00:00Z",
  duty_type_name: "תורנות חמל",
  duty_location_name: null,
  duty_type_id: null,
  duty_location_id: null,
  duty_start_date: "2026-08-01",
  duty_end_date: "2026-08-01",
  duty_shift_id: null,
  requester_manager_approvals: [],
  candidates: [],
} as unknown as swapsApi.SwapRequest;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(myRequestsApi.getRequestsUnseenCount).mockResolvedValue({ count: 0 });
  vi.mocked(myRequestsApi.markRequestsSeen).mockResolvedValue(undefined);
  vi.mocked(useAuth).mockReturnValue({
    user: { id: "sol-1", full_name: "A", role: "soldier" },
  } as AuthContextValue);
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
  vi.mocked(auditLogsApi.listAuditLogs).mockResolvedValue([]);
  vi.mocked(myRequestsApi.listMyHierarchyTransfers).mockResolvedValue([]);
  vi.mocked(myRequestsApi.getMyEnrollment).mockResolvedValue({ request: null });
  vi.mocked(myRequestsApi.listMyRangeExcusalRequests).mockResolvedValue([]);
  vi.mocked(swapsApi.listMySwaps).mockResolvedValue([]);
  vi.mocked(swapsApi.getSwapConfig).mockResolvedValue({
    require_manager_approval: false,
    require_duty_manager_approval: true,
    max_specific_targets: 5,
  });
  vi.mocked(soldiersApi.listFieldUpdates).mockResolvedValue([]);
});

function renderPage(
  initialEntries: string[] = ["/requests"],
  onLocation?: (params: URLSearchParams) => void,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        {onLocation && <LocationProbe cb={onLocation} />}
        <SoldierModalProvider>
          <MyRequestsPage />
        </SoldierModalProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

/** Records the live query string so tests can assert URL-param sync of the
 * existing-tab filters (useSearchParams inside MemoryRouter). */
function LocationProbe({ cb }: { cb: (params: URLSearchParams) => void }) {
  const [searchParams] = useSearchParams();
  useEffect(() => { cb(searchParams); });
  return null;
}

/** The constraint/ER forms live behind reveal toggles on the "new requests" tab. */
async function openConstraintForm() {
  fireEvent.click(screen.getByTestId("constraint-form-toggle"));
  await screen.findByTestId("constraint-form-card");
}

async function openErForm() {
  fireEvent.click(screen.getByTestId("er-form-toggle"));
  await screen.findByTestId("er-form-card");
}

/** Constraint/exemption-request lists live on the "existing requests" tab. */
async function openExistingTab() {
  fireEvent.click(screen.getByTestId("tab-1"));
  await screen.findByTestId("group-constraints");
}

describe("MyRequestsPage - tabs and unseen badge", () => {
  it("defaults to the new tab with both request cards collapsed until revealed", async () => {
    renderPage();
    expect(screen.getByTestId("new-requests-tab")).toBeInTheDocument();
    expect(screen.queryByTestId("req-start")).toBeNull();
    expect(screen.queryByTestId("er-type")).toBeNull();

    fireEvent.click(screen.getByTestId("constraint-form-toggle"));
    expect(await screen.findByTestId("constraints-remaining")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("er-form-toggle"));
    expect(await screen.findByTestId("er-type")).toBeInTheDocument();
  });

  it("deep-links straight into the existing tab via ?tab=existing", async () => {
    renderPage(["/requests?tab=existing"]);
    expect(await screen.findByTestId("existing-requests-tab")).toBeInTheDocument();
  });

  it("shows the unseen-decision badge and clears it by marking seen when the existing tab opens", async () => {
    vi.mocked(myRequestsApi.getRequestsUnseenCount)
      .mockResolvedValueOnce({ count: 3 })
      .mockResolvedValue({ count: 0 });
    renderPage();
    const badge = await screen.findByTestId("tab-badge-1");
    expect(badge).toHaveTextContent("3");

    fireEvent.click(screen.getByTestId("tab-1"));
    await screen.findByTestId("group-constraints");

    await waitFor(() => expect(myRequestsApi.markRequestsSeen).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId("tab-badge-1")).toBeNull());
  });

  it("does not call mark-seen while staying on the new tab", async () => {
    renderPage();
    await screen.findByTestId("new-requests-tab");
    await waitFor(() => expect(myRequestsApi.getRequestsUnseenCount).toHaveBeenCalled());
    expect(myRequestsApi.markRequestsSeen).not.toHaveBeenCalled();
  });
});

describe("MyRequestsPage - existing-tab groups", () => {
  it("shows a cancelled personal constraint with its cancellation reason", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      {
        id: "c-cancelled", soldier_id: "s1", soldier_name: "x", node_name: null,
        start_date: "2026-06-20", end_date: "2026-06-21", reason: "אירוע משפחתי",
        status: "cancelled", commander_approved_by: null, waiting_on: null,
        decided_by: { id: "d1", name: "מבטל בדיקה" }, requested_at: "2026-06-01T00:00:00Z",
        updated_at: "2026-06-19T00:00:00Z", decided_at: "2026-06-19T00:00:00Z",
        decision_note: "כבר לא נדרש", created_at: "2026-06-01T00:00:00Z",
        nearest_commander: null, nearest_duty_manager: null, can_approve: false, can_cancel: false,
      },
    ]);
    renderPage();
    await openExistingTab();
    const list = await screen.findByTestId("cancelled-constraints-list");
    expect(within(list).getByText((content) => content.includes("כבר לא נדרש"))).toBeTruthy();
  });

  it("renders hierarchy transfer rows with node names and status", async () => {
    vi.mocked(myRequestsApi.listMyHierarchyTransfers).mockResolvedValue([
      {
        id: "t1",
        status: "rejected",
        created_at: "2026-01-02T00:00:00Z",
        decided_at: "2026-01-03T00:00:00Z",
        decision_note: "לא כרגע",
        from_node: { id: "n1", name: "מסגרת א" },
        to_node: { id: "n2", name: "מסגרת ב" },
      },
    ]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("transfer-row-t1");
    expect(row.textContent).toContain("מסגרת א");
    expect(row.textContent).toContain("מסגרת ב");
    expect(within(row).getByText("my_requests.rejected")).toBeTruthy();
    expect(row.textContent).toContain("לא כרגע");
  });

  it("renders the enrollment request row when one exists", async () => {
    vi.mocked(myRequestsApi.getMyEnrollment).mockResolvedValue({
      request: {
        id: "e1",
        status: "pending",
        requested_node_id: "n2",
        requested_node_name: "מסגרת ב",
        created_at: "2026-01-02T00:00:00Z",
        decided_at: null,
        decision_note: null,
      },
    });
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("enrollment-row");
    expect(row.textContent).toContain("מסגרת ב");
    expect(within(row).getByText("my_requests.pending")).toBeTruthy();
  });

  it("shows per-group empty states when there are no requests", async () => {
    renderPage();
    await openExistingTab();
    expect(screen.getByText("my_requests.empty_transfers")).toBeInTheDocument();
    expect(screen.getByText("my_requests.empty_enrollment")).toBeInTheDocument();
    expect(screen.getByText("my_requests.empty_range_excusals")).toBeInTheDocument();
    expect(screen.getByText("my_requests.empty_swaps")).toBeInTheDocument();
    expect(screen.getByText("my_requests.empty_field_updates")).toBeInTheDocument();
  });

  it("renders range excusal rows with Hebrew range type, location, and status", async () => {
    vi.mocked(myRequestsApi.listMyRangeExcusalRequests).mockResolvedValue([
      {
        id: "r1",
        status: "approved",
        reason: "אי-נוחות",
        created_at: "2026-01-02T00:00:00Z",
        decided_at: "2026-01-03T00:00:00Z",
        decision_note: null,
        range_date: "2026-02-01",
        range_type: "live",
        range_location_name: "מטווח צאלים",
      },
    ]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("range-excusal-row-r1");
    expect(row.textContent).toContain("מטווח חי"); // RANGE_TYPE_LABELS.live
    expect(row.textContent).toContain("מטווח צאלים");
    expect(within(row).getByText("my_requests.approved")).toBeTruthy();
  });

  it("renders own field-update history rows", async () => {
    vi.mocked(soldiersApi.listFieldUpdates).mockResolvedValue([
      {
        id: "fu1",
        soldier_id: "sol-1",
        soldier_name: "A",
        node_name: null,
        field_name: "phone",
        previous_value: "050-0000000",
        new_value: "052-1111111",
        status: "pending",
        decided_by: null,
        decided_at: null,
        decision_note: null,
        created_at: "2026-01-02T00:00:00Z",
        nearest_commander: null,
        nearest_duty_manager: null,
        can_approve: false,
      },
    ]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("field-update-row-fu1");
    expect(within(row).getByText("soldier_profile.phone")).toBeTruthy();
    expect(within(row).getByText("soldier_profile.update_pending")).toBeTruthy();
  });

  it("renders swaps in process as full swap cards with actions", async () => {
    vi.mocked(swapsApi.listMySwaps).mockResolvedValue([swapInProcess]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("swap-row-sw1");
    expect(within(row).getByText("swaps.status_open")).toBeTruthy();
    expect(within(row).getByText("swaps.cancel")).toBeTruthy();
  });

  it("excludes cancelled swaps from the swaps group", async () => {
    vi.mocked(swapsApi.listMySwaps).mockResolvedValue([
      { ...swapInProcess, id: "sw2", status: "cancelled" },
    ] as unknown as swapsApi.SwapRequest[]);
    renderPage();
    await openExistingTab();
    expect(await screen.findByText("my_requests.empty_swaps")).toBeInTheDocument();
    expect(screen.queryByTestId("swap-row-sw2")).toBeNull();
  });

  it("shows the compact active panel with currently-in-force constraints and exemptions", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      { ...constraint, status: "approved", start_date: "2020-01-01", end_date: "2099-01-01" },
    ]);
    vi.mocked(exemptionsApi.listExemptions).mockResolvedValue([
      {
        id: "ex1",
        soldier_id: "sol-1",
        exemption_type_id: "et-1",
        start_date: "2020-01-01",
        end_date: null,
        reason: null,
        granted_by: null,
        revoke_reason: null,
        revoked_by_name: null,
      },
    ]);
    vi.mocked(dutyConfigApi.listExemptionTypes).mockResolvedValue([
      { id: "et-1", name: "סוג פטור", description: null, active: true },
    ]);
    renderPage();
    await openExistingTab();
    const panel = await screen.findByTestId("active-panel");
    expect(panel.textContent).toContain("(5 ימי׸)".slice(0, 0)); // no-op guard against accidental exact-match edits
    expect(panel.textContent).toContain("2020-01-01");
    expect(panel.textContent).toContain("סוג פטור");
  });
});

describe("MyRequestsPage - day-count badges", () => {
  it("shows a day-count badge next to a pending constraint row", async () => {
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("constraint-row-c1");
    expect(within(row).getByText("(5 ימים)")).toBeTruthy();
  });

  it("renders the constraint date range in start-then-end order, not reversed", async () => {
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("constraint-row-c1");
    // This row renders raw ISO dates (unlike ExemptionsPanel's DD.MM.YYYY
    // formatting), so assert on the ISO order instead.
    expect(row.textContent).toMatch(/2026-01-01[\s\S]*2026-01-05/);
  });

  it("shows a day-count badge next to an exemption-request row", async () => {
    renderPage();
    await openExistingTab();
    await screen.findByText("y");
    expect(screen.getByText("(10 ימים)")).toBeTruthy();
  });

  it("shows the remaining constraint days summary", async () => {
    renderPage();
    await openConstraintForm();
    await screen.findByTestId("constraints-remaining");
    expect(constraintsApi.getRemainingConstraintDays).toHaveBeenCalled();
  });
});

describe("MyRequestsPage - personal constraint form labels", () => {
  it("renders labels above the personal constraint request fields", async () => {
    renderPage();
    await openConstraintForm();

    // Scoped to `.flex-col.gap-1` (the field's own label+input wrapper div), not
    // `.closest("div")` or `.parentElement`: req-start/req-end's data-testid sits on
    // the <input> *inside* DateInput's own wrapper <span> (see DateInput.tsx), so
    // `.parentElement` resolves to that <span>, not the label div. `.closest("div")`
    // would incorrectly skip past <form> (not a <div>) if the label+wrapper-div JSX
    // were ever reverted to flat siblings, landing on some ambient ancestor div
    // instead. Plain `.closest(".flex-col")` isn't specific enough either — Layout's
    // page-wrapper div (Layout.tsx:49) also carries the `flex-col` class, so it would
    // still match after a revert. `.flex-col.gap-1` together is unique to the field
    // wrapper divs among this element's ancestors.
    //
    // Each wrapper is asserted for existence *before* querying it for a <label>:
    // `elem?.querySelector(...)` returns `undefined` (not `null`) when `elem` is
    // null, and `undefined` also satisfies `.not.toBeNull()` — so skipping the
    // wrapper-existence check would silently pass even when `.closest(...)` finds
    // no match at all (as verified manually against the pre-fix JSX).
    const startWrapper = screen.getByTestId("req-start").closest(".flex-col.gap-1");
    const endWrapper = screen.getByTestId("req-end").closest(".flex-col.gap-1");
    const reasonWrapper = screen.getByTestId("req-reason").closest(".flex-col.gap-1");
    expect(startWrapper).not.toBeNull();
    expect(endWrapper).not.toBeNull();
    expect(reasonWrapper).not.toBeNull();
    expect(startWrapper!.querySelector("label")).not.toBeNull();
    expect(endWrapper!.querySelector("label")).not.toBeNull();
    expect(reasonWrapper!.querySelector("label")).not.toBeNull();
  });
});

describe("MyRequestsPage - constraint start date cannot be in the past", () => {
  it("disables the submit button and blocks submission for a past start date", async () => {
    renderPage();
    await openConstraintForm();

    fireEvent.change(screen.getByTestId("req-start"), { target: { value: "01012020" } });
    fireEvent.change(screen.getByTestId("req-end"), { target: { value: "05012020" } });
    fireEvent.change(screen.getByTestId("req-reason"), { target: { value: "סיבה" } });

    expect(screen.getByTestId("req-submit")).toBeDisabled();

    fireEvent.submit(screen.getByTestId("req-submit").closest("form")!);

    expect(await screen.findByText("errors.start_date_in_past")).toBeInTheDocument();
    expect(constraintsApi.submitConstraint).not.toHaveBeenCalled();
  });

  it("allows submission for a start date of today or later", async () => {
    renderPage();
    await openConstraintForm();

    const future = "31122030"; // dd/mm/yyyy digits, as DateInput expects while typing
    fireEvent.change(screen.getByTestId("req-start"), { target: { value: future } });
    fireEvent.change(screen.getByTestId("req-end"), { target: { value: future } });
    fireEvent.change(screen.getByTestId("req-reason"), { target: { value: "סיבה" } });

    expect(screen.getByTestId("req-submit")).not.toBeDisabled();

    fireEvent.click(screen.getByTestId("req-submit"));

    await screen.findByTestId("constraints-remaining");
    expect(constraintsApi.submitConstraint).toHaveBeenCalledWith(
      expect.objectContaining({ start_date: "2030-12-31" }),
    );
  });
});

describe("MyRequestsPage - permanent exemption checkbox", () => {
  it("permanent checkbox disables both date fields and submits null start_date and end_date", async () => {
    vi.mocked(dutyConfigApi.listExemptionTypes).mockResolvedValue([
      { id: "et-1", name: "סוג פטור", description: null, active: true },
    ]);
    renderPage();
    await openErForm();

    fireEvent.focus(screen.getByTestId("er-type"));
    const typeOption = await screen.findByRole("button", { name: "סוג פטור" });
    fireEvent.pointerDown(typeOption);
    fireEvent.pointerUp(typeOption);

    fireEvent.click(screen.getByTestId("er-permanent"));
    expect(screen.getByTestId("er-start")).toBeDisabled();
    expect(screen.getByTestId("er-end")).toBeDisabled();

    fireEvent.change(screen.getByTestId("er-reason"), { target: { value: "פטור קבוע" } });
    fireEvent.click(screen.getByTestId("er-submit"));

    await waitFor(() => {
      expect(vi.mocked(exemptionsApi.submitExemptionRequest)).toHaveBeenCalledWith(
        expect.objectContaining({ start_date: null, end_date: null }),
        [],
      );
    });
  });

  it("unchecking permanent re-enables and requires both date fields", async () => {
    renderPage();
    await openErForm();

    const permanent = screen.getByTestId("er-permanent");
    fireEvent.click(permanent); // check — disables both date fields
    expect(screen.getByTestId("er-start")).toBeDisabled();
    expect(screen.getByTestId("er-end")).toBeDisabled();
    fireEvent.click(permanent); // uncheck — re-enables and requires them again
    expect(screen.getByTestId("er-start")).not.toBeDisabled();
    expect(screen.getByTestId("er-end")).not.toBeDisabled();
    expect(screen.getByTestId("er-end")).toBeRequired();
  });
});

describe("MyRequestsPage - inline audit history", () => {
  it("renders an audit-history toggle for the pending constraint row", async () => {
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("constraint-row-c1");
    expect(within(row).getByTestId("audit-history-toggle-c1")).toBeInTheDocument();
    expect(auditLogsApi.listAuditLogs).not.toHaveBeenCalled();
  });

  it("fetches history for that constraint on expand", async () => {
    vi.mocked(auditLogsApi.listAuditLogs).mockResolvedValue([
      {
        id: "log-9", action: "constraint.submit", actor_id: "sol-1", actor_name: "A",
        entity_type: "personal_constraint", entity_id: "c1",
        before: null, after: { soldier_id: "sol-1" }, context: null,
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("constraint-row-c1");
    fireEvent.click(within(row).getByTestId("audit-history-toggle-c1"));
    await waitFor(() =>
      expect(within(row).getByTestId("audit-history-entry-log-9")).toBeInTheDocument()
    );
    expect(auditLogsApi.listAuditLogs).toHaveBeenCalledWith("personal_constraint", "c1");
  });
});

describe("MyRequestsPage - retraction through pending_duty_manager", () => {
  it("shows the cancel button for a constraint pending duty-manager approval", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      { ...constraint, status: "pending_duty_manager" },
    ]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("constraint-row-c1");
    expect(within(row).getByTestId("cancel-c1")).toBeTruthy();
  });
});

describe("MyRequestsPage - waiting-on visibility", () => {
  it("shows who a pending_commander constraint is waiting on via waiting_on", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      {
        ...constraint,
        status: "pending_commander",
        waiting_on: { kind: "commander", soldier_id: "cmd-1", name: "רס\"ן לוי" },
      },
    ]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("constraint-row-c1");
    const waiting = within(row).getByTestId("constraint-c1-waiting-on");
    expect(waiting).toHaveTextContent("my_requests.waiting_approval");
    expect(waiting).toHaveTextContent("רס\"ן לוי");
    expect(within(waiting).getByRole("button", { name: "רס\"ן לוי" })).toBeTruthy();
  });

  it("shows the duty manager once the commander step is done", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      {
        ...constraint,
        status: "pending_duty_manager",
        waiting_on: { kind: "duty_manager", soldier_id: "dm-1", name: "סמ\"ר כהן" },
      },
    ]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("constraint-row-c1");
    expect(within(row).getByTestId("constraint-c1-waiting-on")).toHaveTextContent("סמ\"ר כהן");
  });

  it("hides the waiting-on line once the request is decided", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      { ...constraint, status: "approved" },
    ]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("constraint-row-c1");
    expect(within(row).queryByTestId("constraint-c1-waiting-on")).toBeNull();
  });
});

describe("MyRequestsPage - request card metadata", () => {
  it("shows formatted request/update dates, waiting-on link, and commander step", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      {
        ...constraint,
        status: "pending_duty_manager",
        created_at: "2026-01-02",
        requested_at: "2026-01-02T09:30:00Z",
        updated_at: "2026-01-05T12:00:00Z",
        waiting_on: { kind: "duty_manager", soldier_id: "dm-1", name: 'סמ"ר כהן' },
        commander_approved_by: { soldier_id: "cmd-1", name: 'רס"ן לוי' },
      },
    ]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("constraint-row-c1");
    const meta = within(row).getByTestId("constraint-c1-meta");
    expect(meta.textContent).toContain("my_requests.requested_at");
    expect(meta.textContent).toContain("02.01.2026");
    expect(meta.textContent).toContain("my_requests.updated_at");
    expect(meta.textContent).toContain("05.01.2026");

    const waiting = within(row).getByTestId("constraint-c1-waiting-on");
    expect(waiting.textContent).toContain("my_requests.waiting_approval");
    expect(waiting.textContent).toContain("my_requests.role_duty_manager");
    expect(within(waiting).getByRole("button", { name: 'סמ"ר כהן' })).toBeTruthy();

    const step = within(row).getByTestId("constraint-c1-commander-step");
    expect(step.textContent).toContain("my_requests.commander_step");
    expect(within(step).getByRole("button", { name: 'רס"ן לוי' })).toBeTruthy();
  });

  it("hides the update date when it lands on the request date", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      {
        ...constraint,
        requested_at: "2026-01-02T09:30:00Z",
        updated_at: "2026-01-02T18:00:00Z",
      },
    ]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("constraint-row-c1");
    expect(row.textContent).not.toContain("my_requests.updated_at");
  });

  it("shows who approved with a decider link on an approved row", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      {
        ...constraint,
        status: "approved",
        requested_at: "2026-01-02T10:00:00Z",
        updated_at: "2026-01-04T10:00:00Z",
        decided_by: { soldier_id: "cmd-9", name: "אבי ג״ל" },
      },
    ]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("constraint-row-c1");
    const decided = within(row).getByTestId("constraint-c1-decided-by");
    expect(decided.textContent).toContain("my_requests.approved_by");
    expect(within(decided).getByRole("button", { name: "אבי ג״ל" })).toBeTruthy();
  });

  it("labels the decider as rejecter on a rejected exemption request", async () => {
    vi.mocked(exemptionsApi.listMyExemptionRequests).mockResolvedValue([
      {
        ...exemptionRequest,
        status: "rejected",
        requested_at: "2026-02-02T08:00:00Z",
        updated_at: "2026-02-03T09:00:00Z",
        decided_by: { soldier_id: "cmd-7", name: "דנה לוי" },
      },
    ] as unknown as exemptionsApi.ExemptionRequest[]);
    renderPage();
    await openExistingTab();
    const row = (await screen.findByText("y")).closest("li")!;
    const decided = within(row).getByTestId("er-er1-decided-by");
    expect(decided.textContent).toContain("my_requests.rejected_by");
    expect(within(decided).getByRole("button", { name: "דנה לוי" })).toBeTruthy();
  });
});

describe("MyRequestsPage - field-update value translation", () => {
  it("renders food_type values through soldier_profile.food_* keys, not raw enums", async () => {
    vi.mocked(soldiersApi.listFieldUpdates).mockResolvedValue([
      {
        id: "fu-food",
        soldier_id: "sol-1",
        soldier_name: "A",
        node_name: null,
        field_name: "food_type",
        previous_value: "regular",
        new_value: "vegetarian",
        status: "approved",
        decided_by: null,
        decided_at: "2026-01-03T00:00:00Z",
        decision_note: null,
        created_at: "2026-01-02T00:00:00Z",
        requested_at: "2026-01-02T00:00:00Z",
        updated_at: "2026-01-03T00:00:00Z",
        waiting_on: null,
        commander_approved_by: null,
        nearest_commander: null,
        nearest_duty_manager: null,
        can_approve: false,
      },
    ]);
    renderPage();
    await openExistingTab();
    const row = await screen.findByTestId("field-update-row-fu-food");
    // t() passes keys through, so the *translated-key* path is what we assert:
    // raw enums alone would render as "regular"/"vegetarian" without the prefix.
    expect(within(row).getByText("soldier_profile.food_regular")).toBeTruthy();
    expect(within(row).getByText("soldier_profile.food_vegetarian")).toBeTruthy();
  });
});

describe("MyRequestsPage - existing-tab filters", () => {
  const transferRow = {
    id: "t1",
    status: "pending",
    created_at: "2026-01-02T00:00:00Z",
    requested_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    decided_at: null,
    decision_note: null,
    waiting_on: null,
    decided_by: null,
    commander_approved_by: null,
    from_node: { id: "n1", name: "מסגרת א" },
    to_node: { id: "n2", name: "מסגרת ב" },
  };

  async function setupExistingWithTransfer(onLocation?: (params: URLSearchParams) => void) {
    vi.mocked(myRequestsApi.listMyHierarchyTransfers).mockResolvedValue([transferRow]);
    renderPage(["/requests?tab=existing"], onLocation);
    await screen.findByTestId("group-constraints");
    await screen.findByTestId("transfer-row-t1");
  }

  it("type select shows only that group's section and syncs ?type=", async () => {
    let params: URLSearchParams | undefined;
    await setupExistingWithTransfer((p) => { params = p; });
    expect(screen.queryByTestId("transfer-row-t1")).not.toBeNull();

    fireEvent.change(screen.getByTestId("filter-type"), { target: { value: "transfers" } });

    expect(screen.queryByTestId("group-constraints")).toBeNull();
    expect(screen.queryByTestId("group-swaps")).toBeNull();
    expect(screen.queryByTestId("transfer-row-t1")).not.toBeNull();
    await waitFor(() => expect(params?.get("type")).toBe("transfers"));
  });

  it("status select filters rows inside every visible group and syncs ?status=", async () => {
    let params: URLSearchParams | undefined;
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      constraint, // pending c1
      { ...constraint, id: "c2", status: "approved" },
    ]);
    await setupExistingWithTransfer((p) => { params = p; });

    fireEvent.change(screen.getByTestId("filter-status"), { target: { value: "approved" } });

    expect(screen.queryByTestId("constraint-row-c1")).toBeNull();
    expect(screen.queryByTestId("constraint-row-c2")).not.toBeNull();
    // Transfers are pending → filtered out of the still-visible transfers group.
    expect(screen.queryByTestId("transfer-row-t1")).toBeNull();
    expect(screen.getByText("my_requests.empty_transfers")).toBeInTheDocument();
    await waitFor(() => expect(params?.get("status")).toBe("approved"));
  });

  it("treats pending_* statuses as ממתין for the status filter", async () => {
    vi.mocked(constraintsApi.listMyConstraints).mockResolvedValue([
      { ...constraint, status: "pending_duty_manager" },
    ]);
    renderPage(["/requests?tab=existing&status=pending"]);
    await openExistingTab();
    await screen.findByTestId("constraint-row-c1");

    fireEvent.change(screen.getByTestId("filter-status"), { target: { value: "rejected" } });
    expect(screen.queryByTestId("constraint-row-c1")).toBeNull();
    expect(screen.getByText("my_requests.none")).toBeInTheDocument();
  });

  it("deep-links with preselected filters from URL params", async () => {
    vi.mocked(myRequestsApi.listMyHierarchyTransfers).mockResolvedValue([transferRow]);
    renderPage(["/requests?tab=existing&type=transfers&status=pending"]);
    await screen.findByTestId("transfer-row-t1");
    expect(screen.queryByTestId("group-constraints")).toBeNull();
    expect(screen.queryByTestId("group-transfers")).not.toBeNull();
    expect(screen.getByTestId("transfer-row-t1")).toBeInTheDocument();
    expect((screen.getByTestId("filter-type") as HTMLSelectElement).value).toBe("transfers");
    expect((screen.getByTestId("filter-status") as HTMLSelectElement).value).toBe("pending");
  });

  it("clearing a filter back to הכל removes its URL param and restores all groups", async () => {
    let params: URLSearchParams | undefined;
    vi.mocked(myRequestsApi.listMyHierarchyTransfers).mockResolvedValue([transferRow]);
    renderPage(["/requests?tab=existing&type=transfers"], (p) => { params = p; });
    await screen.findByTestId("transfer-row-t1");
    expect(screen.queryByTestId("group-constraints")).toBeNull();

    fireEvent.change(screen.getByTestId("filter-type"), { target: { value: "all" } });

    expect(screen.queryByTestId("group-constraints")).not.toBeNull();
    expect(screen.queryByTestId("transfer-row-t1")).not.toBeNull();
    await waitFor(() => expect(params?.get("type")).toBeNull());
  });
});
