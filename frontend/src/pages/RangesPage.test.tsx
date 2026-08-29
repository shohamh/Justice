import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RangesPage from "./RangesPage";
import * as rangesApi from "../api/ranges";
import * as rangeLocationsApi from "../api/rangeLocations";
import * as ineligibleSoldiersApi from "../api/ineligibleSoldiers";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";
import he from "../i18n/he.json";

vi.mock("../api/ranges");
vi.mock("../api/rangeLocations");
vi.mock("../api/ineligibleSoldiers");
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      const value = key.split(".").reduce<unknown>((current, part) => (
        current && typeof current === "object" ? (current as Record<string, unknown>)[part] : undefined
      ), he);
      if (typeof value !== "string") return key;
      return value.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options?.[name] ?? `{{${name}}}`));
    },
  }),
}));
vi.mock("../hooks/useLevelTypes", () => ({
  useLevelTypes: () => ({ levelTypes: [], loading: false, refresh: vi.fn() }),
}));
vi.mock("../api/soldiers", async () => {
  const actual = await vi.importActual<typeof import("../api/soldiers")>("../api/soldiers");
  return { ...actual, listSoldiers: vi.fn().mockResolvedValue([]) };
});
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../components/SoldierSearchAutocomplete", () => ({
  default: (props: { onSelect: (soldier: { id: string } | null) => void }) => (
    <div data-testid="soldier-picker">
      <button data-testid="select-soldier-1" onClick={() => props.onSelect({ id: "soldier-1" })}>
        select
      </button>
    </div>
  ),
}));
vi.mock("../auth/AuthContext", () => ({
  useAuth: vi.fn(),
}));

import { useAuth } from "../auth/AuthContext";

function renderWithQuery(ui: React.ReactElement, initialEntries = ["/ranges"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { client, ...render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>
        <SoldierModalProvider>{ui}</SoldierModalProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  ) };
}

beforeEach(() => {
  vi.clearAllMocks();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mockUser = { id: "me", hierarchy_node_id: "node-1", role: "admin", is_duty_manager: true } as any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(useAuth).mockReturnValue({ user: mockUser } as any);
  vi.mocked(rangesApi.getRangeExcusalRequests).mockResolvedValue([]);
  vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue({ candidates: [], excluded: [] });
  vi.mocked(rangeLocationsApi.listRangeLocations).mockResolvedValue([]);
});

describe("RangesPage", () => {
  it("disables selection for a range the user cannot manage", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-forbidden", hierarchy_node_id: "node-2", range_type: "laser",
        date: "2026-09-01", location: "מטווח ללא הרשאה", required_count: 1,
        reserve_count: 0, status: "planned", assignments: [], can_manage: false,
      },
    ]);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח ללא הרשאה");

    expect(screen.getByTestId("select-range-event-forbidden")).toBeDisabled();
    expect(screen.queryByTestId("bulk-auto-assign-button")).not.toBeInTheDocument();
  });

  it("opens multi-range auto assignment and confirms the ranked primary/reserve plan", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח דרום", required_count: 1,
        reserve_count: 1, status: "planned", assignments: [],
      },
      {
        id: "event-2", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-02", location: "מטווח צפון", required_count: 1,
        reserve_count: 1, status: "planned", assignments: [],
      },
    ]);
    vi.mocked(rangesApi.getRangeCandidates).mockImplementation(async (eventId) => ({
      candidates: [
        { soldier_id: `${eventId}-primary`, full_name: `חייל ראשי ${eventId}`, personal_number: "1", reason_code: "qualified", explanation: "range_valid_expiring:2027-03-01", system_reason_code: "valid_expiring", system_reason_date: "2027-03-01", conflict_warning: null, personal_constraint_conflict: false },
        { soldier_id: `${eventId}-reserve`, full_name: `חייל רזרבה ${eventId}`, personal_number: "2", reason_code: "available_and_balanced", explanation: "range_last_completed:2026-01-01", system_reason_code: "last_completed", system_reason_date: "2026-01-01", conflict_warning: null, personal_constraint_conflict: false },
      ],
      excluded: [],
    }));
    vi.mocked(rangesApi.batchAssignRange).mockResolvedValue([]);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח דרום");
    fireEvent.click(screen.getByTestId("select-range-event-1"));
    fireEvent.click(screen.getByTestId("select-range-event-2"));
    fireEvent.click(screen.getByTestId("bulk-auto-assign-button"));

    expect(await screen.findByTestId("confirm-bulk-auto-assign")).toBeInTheDocument();
    expect(screen.getByTestId("bulk-auto-assign-checkbox-event-1-primary")).toBeChecked();
    expect(screen.getByTestId("bulk-auto-assign-checkbox-event-1-reserve")).toBeChecked();
    expect(screen.getByText("חייל ראשי event-1")).toBeInTheDocument();
    expect(screen.getByText("חייל רזרבה event-1")).toBeInTheDocument();
    expect(screen.getByText("חייל ראשי event-2")).toBeInTheDocument();
    expect(screen.getAllByText("סיבת מערכת").length).toBeGreaterThan(0);
    expect(screen.getAllByText("מטווחים בתוקף, עומדים לפוג ב־01.03.2027").length).toBeGreaterThan(0);
    expect(screen.getAllByText("מטווח אחרון ב־01.01.2026").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTestId("bulk-auto-assign-checkbox-event-1-reserve"));
    expect(screen.getByTestId("confirm-bulk-auto-assign")).toHaveTextContent("(3)");
    fireEvent.click(screen.getByTestId("confirm-bulk-auto-assign"));

    await waitFor(() => expect(rangesApi.batchAssignRange).toHaveBeenCalledTimes(2));
    expect(rangesApi.batchAssignRange).toHaveBeenNthCalledWith(1, "event-1", {
      primaries: ["event-1-primary"], reserves: [],
    });
    expect(rangesApi.batchAssignRange).toHaveBeenNthCalledWith(2, "event-2", {
      primaries: ["event-2-primary"], reserves: ["event-2-reserve"],
    });
  });

  it("keeps successful plans when candidate loading fails for one selected range", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-ok", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01", location: "מטווח תקין", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
      { id: "event-failed", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-02", location: "מטווח שנכשל", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeCandidates).mockImplementation(async (eventId) => {
      if (eventId === "event-failed") throw new Error("candidate request failed");
      return { candidates: [{ soldier_id: "soldier-ok", full_name: "חייל תקין", personal_number: "1", reason_code: "qualified", explanation: "range_valid_expiring:2027-03-01", system_reason_code: "valid_expiring", system_reason_date: "2027-03-01", conflict_warning: null, personal_constraint_conflict: false }], excluded: [] };
    });

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח תקין");
    fireEvent.click(screen.getByTestId("select-range-event-ok"));
    fireEvent.click(screen.getByTestId("select-range-event-failed"));
    fireEvent.click(screen.getByTestId("bulk-auto-assign-button"));

    expect(await screen.findByText("חייל תקין")).toBeInTheDocument();
    const failure = screen.getByText(/מטווח שנכשל.*השיבוץ האוטומטי נכשל/);
    expect(failure).toHaveClass("whitespace-pre-line");
    expect(screen.getByTestId("confirm-bulk-auto-assign")).toHaveTextContent("(1)");
  });

  it("does not fetch planning data in the default schedule view", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([]);

    renderWithQuery(<RangesPage />);

    await screen.findByText("אין מטווחים");
    expect(ineligibleSoldiersApi.getIneligibleSoldiers).not.toHaveBeenCalled();
  });

  it("selects the qualification view from the tab query parameter and fetches its planning data", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([]);
    vi.mocked(ineligibleSoldiersApi.getIneligibleSoldiers).mockResolvedValue({ count: 0, nodes: [], soldiers: [] });

    renderWithQuery(<RangesPage />, ["/ranges?tab=ineligible"]);

    expect(await screen.findByTestId("ineligible-soldiers-view")).toBeInTheDocument();
    expect(ineligibleSoldiersApi.getIneligibleSoldiers).toHaveBeenCalledWith("planning");
  });

  it("selects the locations view from the tab query parameter without fetching planning rows", async () => {
    vi.mocked(rangeLocationsApi.listRangeLocations).mockResolvedValue([
      { id: "loc-1", name: "מטווח דרום", active: true },
    ]);
    vi.mocked(rangeLocationsApi.createRangeLocation).mockResolvedValue({ id: "loc-2", name: "מטווח מזרח", active: true });

    renderWithQuery(<RangesPage />, ["/ranges?tab=locations"]);

    expect(screen.getByRole("tab", { name: "לוח מטווחים" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: "כשירות מטווחים" })).toHaveAttribute("aria-selected", "false");
    expect(await screen.findByRole("tab", { name: "מיקומי מטווחים" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("מטווח דרום")).toBeInTheDocument();
    expect(rangesApi.getRanges).not.toHaveBeenCalled();
    expect(ineligibleSoldiersApi.getIneligibleSoldiers).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("שם המיקום"), { target: { value: "מטווח מזרח" } });
    fireEvent.click(screen.getByRole("button", { name: "הוסף מיקום" }));
    await waitFor(() => expect(rangeLocationsApi.createRangeLocation).toHaveBeenCalledWith({ name: "מטווח מזרח" }));
  });

  it("renders the list of range events", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח דרום", required_count: 4,
        reserve_count: 1, status: "planned", assignments: [],
      },
    ]);

    renderWithQuery(<RangesPage />);

    await waitFor(() => expect(screen.getByText("מטווח דרום")).toBeInTheDocument());
  });

  it("recomputes the primary/reserve fill columns after a roster-changing refetch", async () => {
    // Mirrors what happens when reconciliation removes a redundant duplicate on a
    // FUTURE event and refills it elsewhere: that event's own range_roster_changed
    // notification invalidates the ranges list query, which refetches with updated
    // primary_filled/reserve_filled — no new response field is needed for a
    // commander to see the fill counts change, the existing table already recomputes.
    const baseEvent = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser" as const,
      date: "2026-09-01", location: "מטווח דרום", required_count: 2, reserve_count: 1,
      primary_filled: 1, reserve_filled: 0, status: "planned" as const, assignments: [],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValueOnce([baseEvent]);

    const { client } = renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח דרום");
    expect(screen.getByText("1/2")).toBeInTheDocument();
    expect(screen.getByText("0/1")).toBeInTheDocument();

    vi.mocked(rangesApi.getRanges).mockResolvedValueOnce([
      { ...baseEvent, primary_filled: 2, reserve_filled: 1 },
    ]);
    await client.invalidateQueries({ queryKey: ["ranges"] });

    await waitFor(() => expect(screen.getByText("2/2")).toBeInTheDocument());
    expect(screen.getByText("1/1")).toBeInTheDocument();
    expect(screen.queryByText("1/2")).not.toBeInTheDocument();
  });

  it("renders Hebrew labels for range_type and status instead of raw English", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח דרום", required_count: 4,
        reserve_count: 1, status: "planned", assignments: [],
      },
    ]);

    renderWithQuery(<RangesPage />);

    await waitFor(() => expect(screen.getAllByText("מטווח לייזר").length).toBeGreaterThan(0));
    expect(screen.getAllByText("מתוכנן").length).toBeGreaterThan(0);
    expect(screen.queryByText("laser")).not.toBeInTheDocument();
    expect(screen.queryByText("planned")).not.toBeInTheDocument();
  });

  it("uses the shifts planning header and filter control treatment", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטלול דרום", required_count: 4,
        reserve_count: 1, status: "planned", assignments: [],
      },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
      date: "2026-09-01", location: "מטווח דרום", required_count: 4,
      reserve_count: 1, status: "planned", assignments: [],
    });

    renderWithQuery(<RangesPage />);

    expect(await screen.findByTestId("ranges-page")).toHaveClass("bg-white", "rounded-lg", "shadow", "p-6");
    expect(screen.getByRole("heading", { name: "מטווחים" })).toHaveClass("text-xl", "font-semibold");
    expect(screen.getByTestId("create-event-button")).toHaveClass("bg-blue-600", "text-white", "px-3", "py-1", "rounded", "text-sm");
    expect(await screen.findByLabelText("מתאריך")).toHaveClass("border", "rounded", "p-1", "dark:bg-gray-700");
    expect(screen.getByLabelText("עד תאריך")).toHaveClass("border", "rounded", "p-1", "dark:bg-gray-700");
    expect(screen.getByLabelText("סוג")).toHaveClass("border", "rounded", "p-1", "dark:bg-gray-700");
    expect(screen.getByPlaceholderText("סנן..."))
      .toHaveClass("border", "rounded", "p-1", "text-sm", "w-full", "sm:w-64");
  });

  it("shows export/import links for a manager", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([]);

    renderWithQuery(<RangesPage />);

    await screen.findByTestId("ranges-page");
    expect(screen.getByRole("link", { name: "ייצוא" })).toHaveAttribute("href", "/planning/export");
    expect(screen.getByRole("link", { name: "ייבוא" })).toHaveAttribute("href", "/import");
  });

  it("filters visible ranges and keeps row actions separate from location selection", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח דרום", required_count: 4,
        reserve_count: 1, status: "planned", assignments: [],
      },
      {
        id: "event-2", hierarchy_node_id: "node-1", range_type: "live",
        date: "2026-09-02", location: "מטווח צפון", required_count: 4,
        reserve_count: 1, status: "cancelled", assignments: [],
      },
    ]);

    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
      date: "2026-09-01", location: "מטווח דרום", required_count: 4,
      reserve_count: 1, status: "planned", assignments: [],
    });

    renderWithQuery(<RangesPage />);

    expect(await screen.findByText("מטווח דרום")).toBeInTheDocument();
    expect(screen.getByText("מטווח צפון")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("סטטוס"), { target: { value: "planned" } });
    expect(screen.getByText("מטווח דרום")).toBeInTheDocument();
    expect(screen.queryByText("מטווח צפון")).not.toBeInTheDocument();

    const edit = screen.getByTestId("edit-range-event-1");
    expect(edit).toHaveClass("bg-blue-100", "text-blue-800", "text-[10px]");
    fireEvent.click(edit);
    expect(screen.queryByRole("heading", { name: "מטווח דרום" })).not.toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByTestId("event-1").querySelector("button")!);
    await waitFor(() => expect(rangesApi.getRangeEvent).toHaveBeenCalledWith("event-1"));
  });

  it("opens the assignments editor directly from the שיבוצים row action, without the detail modal", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח דרום", required_count: 4,
        reserve_count: 1, status: "planned", assignments: [],
      },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
      date: "2026-09-01", location: "מטווח דרום", required_count: 4,
      reserve_count: 1, status: "planned", assignments: [],
    });

    renderWithQuery(<RangesPage />);

    await screen.findByText("מטווח דרום");
    fireEvent.click(screen.getByTestId("view-assignments-event-1"));

    await waitFor(() => expect(rangesApi.getRangeEvent).toHaveBeenCalledWith("event-1"));
    expect(await screen.findByRole("heading", { name: "עריכת שיבוצים" })).toBeInTheDocument();
    expect(screen.queryByTestId("range-detail-content")).not.toBeInTheDocument();
  });

  it("uses standard detail metadata, action buttons, and grouped range information", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([{
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [],
      arrival_instructions: "להגיע בשבע", contact_name: "אחראי מטווח", contact_phone: "050-0000000", notes: "ציוד אישי",
    }]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [],
      arrival_instructions: "להגיע בשבע", contact_name: "אחראי מטווח", contact_phone: "050-0000000", notes: "ציוד אישי",
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));

    const dialog = await screen.findByRole("dialog");
    expect(dialog.querySelector("dl")).toHaveClass("grid", "rounded", "p-3");
    expect(screen.queryByTestId("range-detail-actions")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ערוך" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "בטל" })).not.toBeInTheDocument();
    expect(screen.getByTestId("range-detail-information")).toHaveClass("text-gray-800", "dark:text-gray-100");
    expect(screen.getByTestId("range-detail-roster")).toBeInTheDocument();
    expect(screen.getByText("הוראות הגעה:")).toBeInTheDocument();
    expect(screen.getByText("איש קשר:")).toBeInTheDocument();
    expect(screen.getByText("הערות:")).toBeInTheDocument();
  });

  it("shows the delete button disabled (not hidden) when the event has assignments", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-with-assignment", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח עם שיבוץ", required_count: 4,
        reserve_count: 1, primary_filled: 1, reserve_filled: 0, status: "planned",
        assignments: [{
          id: "assignment-1", soldier_id: "soldier-1", is_reserve: false,
          is_draft: false, attendance_status: "pending", note: null,
        }],
      },
    ]);

    renderWithQuery(<RangesPage />);

    const del = await screen.findByTestId("delete-range-event-with-assignment");
    expect(del).toBeDisabled();
    fireEvent.click(del);
    expect(rangesApi.deleteRangeEvent).not.toHaveBeenCalled();
  });

  it("shows the delete button enabled and deletes when the event has no assignments", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-empty", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח ריק", required_count: 4,
        reserve_count: 1, status: "planned", assignments: [],
      },
    ]);
    vi.mocked(rangesApi.deleteRangeEvent).mockResolvedValue(undefined);

    renderWithQuery(<RangesPage />);

    const del = await screen.findByTestId("delete-range-event-empty");
    expect(del).not.toBeDisabled();
    fireEvent.click(del);
    fireEvent.click(await screen.findByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(rangesApi.deleteRangeEvent).toHaveBeenCalledWith("event-empty"));
  });

  it("keeps detail selected when Escape closes the edit modal", async () => {
    const range = {
      id: "event-edit", hierarchy_node_id: "node-1", range_type: "laser" as const,
      date: "2026-09-01", location: "מטווח עריכה", required_count: 1, reserve_count: 0,
      status: "planned" as const, assignments: [],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([range]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(range);

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח עריכה"));
    expect(await screen.findByTestId("range-detail-content")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("edit-range-event-edit"));
    // The edit button fetches fresh event data before opening the form
    // (unlike the cancel dialog below, which opens synchronously) — press
    // Escape only once the form has actually mounted, otherwise it's still
    // caught by the still-open detail modal's own Escape handler instead.
    await screen.findByTestId("range-form");
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByTestId("range-form")).not.toBeInTheDocument());
    expect(screen.getByTestId("range-detail-content")).toBeInTheDocument();
  });

  it("keeps detail selected when Escape closes the cancel dialog", async () => {
    const range = {
      id: "event-cancel", hierarchy_node_id: "node-1", range_type: "laser" as const,
      date: "2026-09-01", location: "מטווח ביטול", required_count: 1, reserve_count: 0,
      status: "planned" as const, assignments: [],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([range]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(range);

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח ביטול"));
    expect(await screen.findByTestId("range-detail-content")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("cancel-range-event-cancel"));
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("heading", { name: "ביטול מטווח" })).not.toBeInTheDocument());
    expect(screen.getByTestId("range-detail-content")).toBeInTheDocument();
  });

  it("selects rows via checkboxes and shows the bulk action bar once at least one is selected", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
      { id: "event-2", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-02",
        location: "מטווח ב", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
    ]);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח א");

    expect(screen.queryByTestId("range-bulk-action-bar")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("select-range-event-1"));
    expect(await screen.findByTestId("range-bulk-action-bar")).toHaveTextContent("1 נבחרו");
    fireEvent.click(screen.getByTestId("select-range-event-2"));
    expect(screen.getByTestId("range-bulk-action-bar")).toHaveTextContent("2 נבחרו");
    fireEvent.click(screen.getByTestId("select-range-event-1"));
    expect(screen.getByTestId("range-bulk-action-bar")).toHaveTextContent("1 נבחרו");
  });

  it("selects all visible manageable range rows from the table corner checkbox", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01", location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
      { id: "event-2", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-02", location: "מטווח ב", required_count: 1, reserve_count: 0, status: "planned", assignments: [], can_manage: false },
      { id: "event-3", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-03", location: "מטווח ג", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
    ]);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח א");

    const selectAll = screen.getByTestId("select-all-ranges");
    fireEvent.click(selectAll);
    expect(screen.getByTestId("select-range-event-1")).toBeChecked();
    expect(screen.getByTestId("select-range-event-2")).toBeDisabled();
    expect(screen.getByTestId("select-range-event-3")).toBeChecked();
    expect(screen.getByTestId("range-bulk-action-bar")).toHaveTextContent("2 נבחרו");

    fireEvent.click(selectAll);
    expect(screen.getByTestId("select-range-event-1")).not.toBeChecked();
    expect(screen.getByTestId("select-range-event-3")).not.toBeChecked();
  });

  it("shows range list loading and request failures through the planning table", async () => {
    let resolve!: (rows: rangesApi.RangeEvent[]) => void;
    vi.mocked(rangesApi.getRanges).mockReturnValue(new Promise(r => { resolve = r; }));
    renderWithQuery(<RangesPage />);
    expect(screen.getByRole("status")).toHaveTextContent("טוען");
    resolve([]);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("אין מטווחים"));

    vi.mocked(rangesApi.getRanges).mockRejectedValueOnce(new Error("request failed"));
    renderWithQuery(<RangesPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("טעינת המטווחים נכשלה");
  });
});

describe("RangesPage create event", () => {
  it("creates a new range event via the create form", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([]);
    vi.mocked(rangesApi.createRangeEvent).mockResolvedValue({
      id: "event-2", hierarchy_node_id: "node-1", range_type: "live",
      date: "2026-10-01", location: "מטווח צפון", required_count: 6,
      reserve_count: 2, status: "planned", assignments: [],
    });
    vi.mocked(rangeLocationsApi.listRangeLocations).mockResolvedValue([
      { id: "loc-1", name: "מטווח צפון", active: true },
    ]);

    renderWithQuery(<RangesPage />);

    fireEvent.click(await screen.findByTestId("create-event-button"));
    expect(await screen.findByTestId("create-event-form")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("new-range-type"), { target: { value: "live" } });
    fireEvent.change(screen.getByTestId("new-date"), { target: { value: "2026-10-01" } });
    fireEvent.focus(screen.getByTestId("new-range-location"));
    const locationOption = await screen.findByText("מטווח צפון");
    fireEvent.pointerDown(locationOption);
    fireEvent.pointerUp(locationOption);
    fireEvent.change(screen.getByTestId("new-start-time"), { target: { value: "08:00" } });
    fireEvent.change(screen.getByTestId("new-end-time"), { target: { value: "12:00" } });
    fireEvent.change(screen.getByTestId("new-required-count"), { target: { value: "6" } });
    fireEvent.change(screen.getByTestId("new-reserve-count"), { target: { value: "2" } });
    fireEvent.change(screen.getByTestId("new-contact-name"), { target: { value: "אחראי מטווח" } });
    fireEvent.change(screen.getByTestId("new-contact-phone"), { target: { value: "050-0000000" } });
    fireEvent.change(screen.getByLabelText("הוראות הגעה"), { target: { value: "להגיע בשמונה" } });
    fireEvent.change(screen.getByLabelText("הערות"), { target: { value: "ציוד אישי" } });

    fireEvent.click(screen.getByText("שמור"));

    await waitFor(() =>
      expect(rangesApi.createRangeEvent).toHaveBeenCalledWith({
        hierarchy_node_id: "node-1",
        range_type: "live",
        date: "2026-10-01",
        range_location_id: "loc-1",
        start_time: "08:00",
        end_time: "12:00",
        arrival_instructions: "להגיע בשמונה",
        contact_name: "אחראי מטווח",
        contact_phone: "050-0000000",
        notes: "ציוד אישי",
        required_count: 6,
        reserve_count: 2,
      }),
    );
    await waitFor(() => expect(screen.queryByTestId("create-event-form")).not.toBeInTheDocument());
  });
});

// Assignment mutations are covered by RangeEditAssignmentsModal.test.tsx.

describe("RangesPage read-only mode for commanders", () => {
  it("hides add/remove controls for a commander (not a duty manager)", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const mockUser = { id: "u1", hierarchy_node_id: "node-1", role: "commander", is_commander: true, is_duty_manager: false } as any;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(useAuth).mockReturnValue({ user: mockUser } as any);
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned",
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false,
        attendance_status: "pending", note: null }],
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));

    expect(await screen.findByTestId("range-detail-content")).toBeInTheDocument();
    expect(screen.queryByTestId("add-soldier-button")).not.toBeInTheDocument();
    expect(screen.queryByText("הסר")).not.toBeInTheDocument();
    expect(screen.queryByTestId("range-detail-actions")).not.toBeInTheDocument();
    expect(screen.queryByTestId("edit-range-assignments")).not.toBeInTheDocument();
  });

  it("hides the attendance panel for a commander even on a past event", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const mockUser = { id: "u1", hierarchy_node_id: "node-1", role: "commander", is_commander: true, is_duty_manager: false } as any;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(useAuth).mockReturnValue({ user: mockUser } as any);
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2020-01-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "completed", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2020-01-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "completed",
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false,
        attendance_status: "pending", note: null }],
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));

    await waitFor(() => expect(screen.getByText("s1")).toBeInTheDocument());
    expect(screen.queryByTestId("present-a1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("no-show-a1")).not.toBeInTheDocument();
  });
});

describe("RangesPage attendance panel", () => {
  it("shows the attendance panel for a past event when the API allows attendance editing", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2020-01-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "completed", assignments: [], can_edit_attendance: true },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2020-01-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "completed", can_edit_attendance: true,
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false,
        attendance_status: "pending", note: null }],
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));

    expect(await screen.findByTestId("present-a1")).toBeInTheDocument();
    expect(screen.getByTestId("no-show-a1")).toBeInTheDocument();
  });

  it("does not show the attendance panel for a future event", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned",
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false,
        attendance_status: "pending", note: null }],
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));

    await waitFor(() => expect(screen.getByText("s1")).toBeInTheDocument());
    expect(screen.queryByTestId("present-a1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("no-show-a1")).not.toBeInTheDocument();
  });

  it("excludes draft assignments from attendance controls", async () => {
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser" as const, date: "2020-01-01",
      location: "מטווח דרום", required_count: 2, reserve_count: 0, status: "completed" as const, can_edit_attendance: true,
      assignments: [
        { id: "confirmed", soldier_id: "s1", is_reserve: false, is_draft: false,
          attendance_status: "pending" as const, note: null },
        { id: "draft", soldier_id: "s2", is_reserve: false, is_draft: true,
          attendance_status: "pending" as const, note: null },
      ],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    expect(await screen.findByTestId("present-confirmed")).toBeInTheDocument();
    expect(screen.queryByTestId("present-draft")).not.toBeInTheDocument();
    expect(screen.queryByTestId("no-show-draft")).not.toBeInTheDocument();
  });
});

describe("RangesPage deep link via ?event=", () => {
  it("auto-selects the event id from the query param without a click", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [],
    });

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    await waitFor(() => expect(rangesApi.getRangeEvent).toHaveBeenCalledWith("event-1"));
    expect(await screen.findAllByText("מטווח דרום")).not.toHaveLength(0);
  });
});


describe("RangesPage excusal", () => {
  it("requires a reason before a soldier can excuse an upcoming assignment", async () => {
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser" as const,
      date: "2099-09-01", location: "מטווח דרום", required_count: 1, reserve_count: 1,
      status: "planned" as const,
      assignments: [{ id: "a1", soldier_id: "me", is_reserve: false, is_draft: false,
        attendance_status: "pending" as const, note: null }],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);
    vi.mocked(rangesApi.excuseRangeAssignment).mockResolvedValue({
      id: "request-1", range_assignment_id: "a1", requested_by: "me", reason: "reason",
      status: "pending", decided_by: null, decided_at: null, decision_note: null,
      promoted_assignment_id: null,
    });

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);
    fireEvent.click(await screen.findByRole("button", { name: "אני לא אוכל להגיע" }));
    expect(screen.queryByTestId("excuse-button-a1")).not.toBeInTheDocument();
    const submit = screen.getByTestId("submit-excuse-button");
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("סיבת היעדרות"), { target: { value: "reason" } });
    expect(submit).not.toBeDisabled();
    fireEvent.click(submit);
    await waitFor(() => expect(rangesApi.excuseRangeAssignment).toHaveBeenCalledWith("event-1", "a1", "reason"));
  });
});

describe("RangesPage assignment editor integration", () => {
  it("refreshes both the ranges list and selected detail after removing an assignment", async () => {
    const event = {
      id: "event-refresh", hierarchy_node_id: "node-1", range_type: "laser" as const,
      date: "2026-09-01", location: "מטווח לרענון", required_count: 1, reserve_count: 0,
      status: "planned" as const,
      assignments: [{ id: "assignment-refresh", soldier_id: "s1", is_reserve: false, is_draft: false,
        attendance_status: "pending" as const, note: null }],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);
    vi.mocked(rangesApi.removeRangeAssignment).mockResolvedValue(undefined);

    const { client } = renderWithQuery(<RangesPage />);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    fireEvent.click(await screen.findByText("מטווח לרענון"));
    fireEvent.click(screen.getByTestId("view-assignments-event-refresh"));
    fireEvent.click(await screen.findByTestId("remove-assignment-assignment-refresh"));
    fireEvent.change(await screen.findByLabelText("סיבת ההסרה"), { target: { value: "חייל שוחרר" } });
    fireEvent.click(screen.getByTestId("input-dialog-confirm"));

    await waitFor(() => expect(rangesApi.removeRangeAssignment).toHaveBeenCalledWith("event-refresh", "assignment-refresh", "חייל שוחרר"));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["ranges"] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["ranges", "event-refresh"] });
  });

  it("keeps assignment mutations out of the range detail content", async () => {
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser" as const,
      date: "2026-09-01", location: "מטווח דרום", required_count: 1, reserve_count: 1,
      status: "planned" as const,
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false,
        attendance_status: "pending" as const, note: null }],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));

    expect(await screen.findByTestId("range-detail-content")).toBeInTheDocument();
    expect(screen.queryByTestId("edit-range-assignments")).not.toBeInTheDocument();
    expect(screen.queryByTestId("add-soldier-button")).not.toBeInTheDocument();
    expect(screen.queryByText("הסר")).not.toBeInTheDocument();
  });

  it("closes only the assignment editor on Escape and preserves the selected detail", async () => {
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser" as const,
      date: "2026-09-01", location: "מטווח דרום", required_count: 1, reserve_count: 0,
      status: "planned" as const, assignments: [],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByTestId("view-assignments-event-1"));

    expect(await screen.findByRole("heading", { name: "עריכת שיבוצים" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("heading", { name: "עריכת שיבוצים" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByText("מטווח דרום"));
    expect(await screen.findByTestId("range-detail-content")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "מטווח דרום" })).toBeInTheDocument();
  });

  it("bulk-deletes only the selected events with no assignments, skipping the rest", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-empty", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח ריק", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
      { id: "event-full", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-02",
        location: "מטווח מלא", required_count: 1, reserve_count: 0, status: "planned",
        assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false, attendance_status: "pending", note: null }] },
    ]);
    vi.mocked(rangesApi.deleteRangeEvent).mockResolvedValue(undefined);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח ריק");
    fireEvent.click(screen.getByTestId("select-range-event-empty"));
    fireEvent.click(screen.getByTestId("select-range-event-full"));
    fireEvent.click(await screen.findByTestId("bulk-delete-button"));
    fireEvent.click(await screen.findByTestId("confirm-dialog-confirm"));

    await waitFor(() => expect(rangesApi.deleteRangeEvent).toHaveBeenCalledWith("event-empty"));
    expect(rangesApi.deleteRangeEvent).not.toHaveBeenCalledWith("event-full");
  });

  it("bulk-cancels selected active events with a shared reason", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
      { id: "event-2", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-02",
        location: "מטווח ב", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.cancelRangeEvent).mockResolvedValue(undefined);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח א");
    fireEvent.click(screen.getByTestId("select-range-event-1"));
    fireEvent.click(screen.getByTestId("select-range-event-2"));
    fireEvent.click(await screen.findByTestId("bulk-cancel-button"));
    fireEvent.change(await screen.findByLabelText("סיבת הביטול"), { target: { value: "גשם" } });
    fireEvent.click(screen.getByTestId("confirm-bulk-cancel-button"));

    await waitFor(() => expect(rangesApi.cancelRangeEvent).toHaveBeenCalledWith("event-1", "גשם"));
    expect(rangesApi.cancelRangeEvent).toHaveBeenCalledWith("event-2", "גשם");
  });

  it("bulk-clears all assignments from selected events by fetching each event's real assignments", async () => {
    // The list row itself carries an empty assignments array (matching the real
    // list endpoint, which never includes assignments) — bulkClear must fetch
    // event detail to find what to remove, not read off the stale list row.
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned",
        assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false, attendance_status: "pending", note: null }] },
    );
    vi.mocked(rangesApi.removeRangeAssignment).mockResolvedValue(undefined);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח א");
    fireEvent.click(screen.getByTestId("select-range-event-1"));
    fireEvent.click(await screen.findByTestId("bulk-clear-button"));
    fireEvent.change(await screen.findByLabelText("סיבת הניקוי (תחול על כל השיבוצים שינוקו)"), { target: { value: "ניקוי כללי" } });
    fireEvent.click(screen.getByTestId("input-dialog-confirm"));

    await waitFor(() => expect(rangesApi.getRangeEvent).toHaveBeenCalledWith("event-1"));
    await waitFor(() => expect(rangesApi.removeRangeAssignment).toHaveBeenCalledWith("event-1", "a1", "ניקוי כללי"));
  });

  it("shows an error message when a bulk action fails", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
    ]);
    // bulkClear (Promise.all under the hood) rejects on the first failure, unlike
    // bulkDelete's Promise.allSettled which never rejects — exercise the catch path here.
    vi.mocked(rangesApi.getRangeEvent).mockRejectedValue(new Error("boom"));

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח א");
    fireEvent.click(screen.getByTestId("select-range-event-1"));
    fireEvent.click(await screen.findByTestId("bulk-clear-button"));
    fireEvent.change(await screen.findByLabelText("סיבת הניקוי (תחול על כל השיבוצים שינוקו)"), { target: { value: "ניקוי כללי" } });
    fireEvent.click(screen.getByTestId("input-dialog-confirm"));

    expect(await screen.findByRole("alert")).toHaveTextContent("מטווח א");
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });

  it("does not offer clearing assignments for a range that already happened", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-past", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-08-01",
        location: "מטווח שכבר התקיים", required_count: 1, reserve_count: 0, status: "completed", assignments: [] },
    ]);
    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח שכבר התקיים");
    fireEvent.click(screen.getByTestId("select-range-event-past"));

    expect(screen.getByTestId("bulk-clear-button")).toBeDisabled();
    expect(screen.getByText(/לא ניתן לנקות מטווחים שכבר התקיימו/)).toBeInTheDocument();
    expect(rangesApi.getRangeEvent).not.toHaveBeenCalled();
  });

  it("filters bulk-cancel to planned events only and labels the button with the filtered count", async () => {
    vi.mocked(rangesApi.cancelRangeEvent).mockClear();
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
      { id: "event-2", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-02",
        location: "מטווח ב", required_count: 1, reserve_count: 0, status: "cancelled", assignments: [] },
    ]);
    vi.mocked(rangesApi.cancelRangeEvent).mockResolvedValue(undefined);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח א");
    fireEvent.click(screen.getByTestId("select-range-event-1"));
    fireEvent.click(screen.getByTestId("select-range-event-2"));

    const cancelButton = await screen.findByTestId("bulk-cancel-button");
    expect(cancelButton).toHaveTextContent("בטל מטווחים (1)");
    fireEvent.click(cancelButton);
    fireEvent.change(await screen.findByLabelText("סיבת הביטול"), { target: { value: "גשם" } });
    fireEvent.click(screen.getByTestId("confirm-bulk-cancel-button"));

    await waitFor(() => expect(rangesApi.cancelRangeEvent).toHaveBeenCalledWith("event-1", "גשם"));
    expect(rangesApi.cancelRangeEvent).toHaveBeenCalledTimes(1);
  });

  it("does not show selection checkboxes or the bulk action bar for a non-manager", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const mockUser = { id: "u1", hierarchy_node_id: "node-1", role: "soldier", is_duty_manager: false } as any;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(useAuth).mockReturnValue({ user: mockUser } as any);
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
    ]);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח א");

    expect(screen.queryByTestId("select-range-event-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("range-bulk-action-bar")).not.toBeInTheDocument();
  });
});
