import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import MyRequestsPage from "./MyRequestsPage";
import * as constraintsApi from "../api/constraints";
import * as exemptionsApi from "../api/exemptions";
import * as dutyConfigApi from "../api/dutyConfig";
import * as auditLogsApi from "../api/auditLogs";
import { useAuth } from "../auth/AuthContext";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../api/constraints");
vi.mock("../api/exemptions");
vi.mock("../api/dutyConfig");
vi.mock("../api/auditLogs");
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
  vi.mocked(auditLogsApi.listAuditLogs).mockResolvedValue([]);
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

  it("renders the constraint date range in start-then-end order, not reversed", async () => {
    renderPage();
    const row = await screen.findByTestId("constraint-row-c1");
    // This row renders raw ISO dates (unlike ExemptionsPanel's DD.MM.YYYY
    // formatting), so assert on the ISO order instead.
    expect(row.textContent).toMatch(/2026-01-01[\s\S]*2026-01-05/);
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

describe("MyRequestsPage - personal constraint form labels", () => {
  it("renders labels above the personal constraint request fields", async () => {
    renderPage();
    await screen.findByTestId("constraints-remaining");

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
    await screen.findByTestId("constraints-remaining");

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
    await screen.findByTestId("constraints-remaining");

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
    await screen.findByTestId("constraints-remaining");

    fireEvent.focus(screen.getByTestId("er-type"));
    const typeOption = screen.getByRole("button", { name: "סוג פטור" });
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
    await screen.findByTestId("constraints-remaining");

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
    const row = await screen.findByTestId("constraint-row-c1");
    expect(within(row).getByTestId("cancel-c1")).toBeTruthy();
  });
});
