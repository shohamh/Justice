import { fireEvent, render, screen, within } from "@testing-library/react";
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
