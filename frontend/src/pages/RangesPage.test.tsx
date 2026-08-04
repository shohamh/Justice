import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RangesPage from "./RangesPage";
import * as rangesApi from "../api/ranges";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";

vi.mock("../api/ranges");
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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mockUser = { id: "me", hierarchy_node_id: "node-1", role: "admin", is_duty_manager: true } as any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(useAuth).mockReturnValue({ user: mockUser } as any);
  vi.mocked(rangesApi.getRangeExcusalRequests).mockResolvedValue([]);
});

describe("RangesPage", () => {
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

  it("renders Hebrew labels for range_type and status instead of raw English", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח דרום", required_count: 4,
        reserve_count: 1, status: "planned", assignments: [],
      },
    ]);

    renderWithQuery(<RangesPage />);

    await waitFor(() => expect(screen.getAllByText("לייזר").length).toBeGreaterThan(0));
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

  it("does not offer deletion when assignments exist despite stale filled counts", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-with-assignment", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח עם שיבוץ", required_count: 4,
        reserve_count: 1, primary_filled: 0, reserve_filled: 0, status: "planned",
        assignments: [{
          id: "assignment-1", soldier_id: "soldier-1", is_reserve: false,
          is_draft: false, attendance_status: "pending", note: null,
        }],
      },
    ]);

    renderWithQuery(<RangesPage />);

    expect(window.confirm).not.toHaveBeenCalled();
    expect(screen.queryByTestId("delete-range-event-with-assignment")).not.toBeInTheDocument();
    expect(rangesApi.deleteRangeEvent).not.toHaveBeenCalled();
  });

  it("uses list summary counts for production list responses with no inline assignments", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([{
      id: "event-summary-assigned", hierarchy_node_id: "node-1", range_type: "laser",
      date: "2026-09-01", location: "מטווח עם סיכום שיבוץ", required_count: 1,
      reserve_count: 0, primary_filled: 1, reserve_filled: 0, status: "planned", assignments: [],
    }]);

    renderWithQuery(<RangesPage />);

    await screen.findByText("מטווח עם סיכום שיבוץ");
    expect(screen.queryByTestId("delete-range-event-summary-assigned")).not.toBeInTheDocument();
  });

  it("rechecks authoritative detail before deleting a range with draft assignments", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const listed = {
      id: "event-detail-assigned", hierarchy_node_id: "node-1", range_type: "laser" as const,
      date: "2026-09-01", location: "מטווח עם טיוטת שיבוץ", required_count: 1,
      reserve_count: 0, primary_filled: 0, reserve_filled: 0, status: "planned" as const, assignments: [],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([listed]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      ...listed,
      assignments: [{ id: "draft-1", soldier_id: "s1", is_reserve: false, is_draft: true, attendance_status: "pending", note: null }],
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByTestId("delete-range-event-detail-assigned"));

    await waitFor(() => expect(rangesApi.getRangeEvent).toHaveBeenCalledWith("event-detail-assigned"));
    expect(rangesApi.deleteRangeEvent).not.toHaveBeenCalled();
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

    renderWithQuery(<RangesPage />);

    fireEvent.click(await screen.findByTestId("create-event-button"));
    expect(await screen.findByTestId("create-event-form")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("new-range-type"), { target: { value: "live" } });
    fireEvent.change(screen.getByTestId("new-date"), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByTestId("new-location"), { target: { value: "מטווח צפון" } });
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
        location: "מטווח צפון",
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

// Assignment mutations are covered by RangeEditAssignmentsModal.test.tsx.
/* Obsolete inline-assignment tests removed: assignment mutations now live in RangeEditAssignmentsModal. */
/*
  it("shows the auto-assign button when slots remain and renders draft assignments", async () => {
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned" as const, assignments: [],
    };
    const draft = {
      id: "assignment-1", soldier_id: "soldier-1", is_reserve: false, is_draft: true,
      attendance_status: "pending" as const, note: null,
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent)
      .mockResolvedValueOnce({ ...event, assignments: [] })
      .mockResolvedValue({ ...event, assignments: [draft] });
    vi.mocked(rangesApi.autoAssignRange).mockResolvedValue({ created: [draft], shortfall: 0 });

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    const autoAssignButton = await screen.findByTestId("auto-assign-button");
    expect(autoAssignButton).toBeInTheDocument();

    fireEvent.click(autoAssignButton);

    await waitFor(() => expect(rangesApi.autoAssignRange).toHaveBeenCalledWith("event-1"));
    expect(await screen.findByTestId("draft-badge")).toBeInTheDocument();
    expect(screen.getByText("טיוטה")).toBeInTheDocument();
  });

  it("shows the auto-assign button when the reserve quota remains despite a full total roster", async () => {
    const assignments = Array.from({ length: 3 }, (_, i) => ({
      id: `a${i}`, soldier_id: `s${i}`, is_reserve: false, is_draft: false,
      attendance_status: "pending" as const, note: null,
    }));
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 2, reserve_count: 1, status: "planned" as const, assignments,
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    await waitFor(() => expect(screen.getByText("s0")).toBeInTheDocument());
    expect(screen.getByTestId("auto-assign-button")).toBeInTheDocument();
  });

  it("disables auto-assign while the request is pending", async () => {
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 1, reserve_count: 0, status: "planned" as const,
      assignments: [],
    };
    let resolveAutoAssign!: (result: rangesApi.AutoAssignResult) => void;
    const pendingAutoAssign = new Promise<rangesApi.AutoAssignResult>((resolve) => {
      resolveAutoAssign = resolve;
    });
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);
    vi.mocked(rangesApi.autoAssignRange).mockReturnValue(pendingAutoAssign);

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    const button = await screen.findByTestId("auto-assign-button");
    fireEvent.click(button);

    await waitFor(() => expect(button).toBeDisabled());
    resolveAutoAssign({ created: [], shortfall: 1 });
    await waitFor(() => expect(button).not.toBeDisabled());
  });

  it("hides the auto-assign button when the roster is full", async () => {
    const assignments = Array.from({ length: 5 }, (_, i) => ({
      id: `a${i}`, soldier_id: `s${i}`, is_reserve: i === 4, is_draft: false,
      attendance_status: "pending" as const, note: null,
    }));
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned" as const, assignments,
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    await waitFor(() => expect(screen.getByText("s0")).toBeInTheDocument());
    expect(screen.queryByTestId("auto-assign-button")).not.toBeInTheDocument();
  });

  it("shows a shortfall banner when auto-assign cannot fill all slots", async () => {
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned" as const, assignments: [],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({ ...event, assignments: [] });
    vi.mocked(rangesApi.autoAssignRange).mockResolvedValue({ created: [], shortfall: 2 });

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    fireEvent.click(await screen.findByTestId("auto-assign-button"));

    await waitFor(() => expect(screen.getByTestId("shortfall-banner")).toBeInTheDocument());
    expect(screen.getByTestId("shortfall-banner")).toHaveTextContent("2");
  });

  it("clears the shortfall banner when switching to another event", async () => {
    const eventA = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned" as const, assignments: [],
    };
    const eventB = {
      id: "event-2", hierarchy_node_id: "node-1", range_type: "live", date: "2026-10-01",
      location: "מטווח צפון", required_count: 6, reserve_count: 2, status: "planned" as const,
      assignments: [{ id: "b1", soldier_id: "s-b", is_reserve: false, is_draft: false,
        attendance_status: "pending" as const, note: null }],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([eventA, eventB]);
    vi.mocked(rangesApi.getRangeEvent).mockImplementation(async (id) => (id === eventB.id ? eventB : eventA));
    vi.mocked(rangesApi.autoAssignRange).mockResolvedValue({ created: [], shortfall: 2 });

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    fireEvent.click(await screen.findByTestId("auto-assign-button"));
    await waitFor(() => expect(screen.getByTestId("shortfall-banner")).toBeInTheDocument());

    fireEvent.click(screen.getByText("מטווח צפון"));

    await waitFor(() => expect(screen.getByText("s-b")).toBeInTheDocument());
    await waitFor(() => expect(screen.queryByTestId("shortfall-banner")).not.toBeInTheDocument());
  });
});
*/

/* Obsolete inline-assignment tests removed: assignment mutations now live in RangeEditAssignmentsModal. */
/*
  it("confirms a draft assignment from the roster", async () => {
    const draft = {
      id: "a1", soldier_id: "s1", is_reserve: false, is_draft: true,
      attendance_status: "pending" as const, note: null,
    };
    const confirmed = { ...draft, is_draft: false };
    let assignments: rangesApi.RangeAssignment[] = [draft];
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned" as const,
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([{ ...event, assignments }]);
    vi.mocked(rangesApi.getRangeEvent).mockImplementation(async () => ({ ...event, assignments }));
    vi.mocked(rangesApi.confirmDraftAssignment).mockImplementation(async (_eventId, assignmentId) => {
      assignments = assignments.map((a) => (a.id === assignmentId ? confirmed : a));
      return confirmed;
    });

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    const confirmButton = await screen.findByTestId("confirm-draft-button");
    fireEvent.click(confirmButton);

    await waitFor(() => expect(rangesApi.confirmDraftAssignment).toHaveBeenCalledWith("event-1", "a1"));
    await waitFor(() => expect(screen.queryByTestId("draft-badge")).not.toBeInTheDocument());
  });

  it("confirms all drafts via the confirm-all button", async () => {
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned" as const,
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: true,
        attendance_status: "pending" as const, note: null }],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);
    vi.mocked(rangesApi.confirmAllDrafts).mockResolvedValue([]);

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    fireEvent.click(await screen.findByTestId("confirm-all-button"));

    await waitFor(() => expect(rangesApi.confirmAllDrafts).toHaveBeenCalledWith("event-1"));
  });

  it("disables all confirm controls while a confirm request is pending", async () => {
    const draft = {
      id: "a1", soldier_id: "s1", is_reserve: false, is_draft: true,
      attendance_status: "pending" as const, note: null,
    };
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 1, reserve_count: 0, status: "planned" as const,
      assignments: [draft],
    };
    let resolveConfirm!: (assignment: rangesApi.RangeAssignment) => void;
    const pendingConfirm = new Promise<rangesApi.RangeAssignment>((resolve) => {
      resolveConfirm = resolve;
    });
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);
    vi.mocked(rangesApi.confirmDraftAssignment).mockReturnValue(pendingConfirm);

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    const rowConfirm = await screen.findByTestId("confirm-draft-button");
    const confirmAll = screen.getByTestId("confirm-all-button");
    fireEvent.click(rowConfirm);

    await waitFor(() => expect(rowConfirm).toBeDisabled());
    expect(confirmAll).toBeDisabled();
    resolveConfirm({ ...draft, is_draft: false });
    await waitFor(() => expect(rowConfirm).not.toBeDisabled());
  });

  it("hides confirm controls when the event is not planned", async () => {
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2020-01-01",
      location: "מטווח דרום", required_count: 1, reserve_count: 0, status: "completed" as const,
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: true,
        attendance_status: "pending" as const, note: null }],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    expect(await screen.findByTestId("draft-badge")).toBeInTheDocument();
    expect(screen.queryByTestId("confirm-draft-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("confirm-all-button")).not.toBeInTheDocument();
  });

  it("removes a draft via the existing remove button", async () => {
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned" as const,
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: true,
        attendance_status: "pending" as const, note: null }],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);
    vi.mocked(rangesApi.removeRangeAssignment).mockResolvedValue(undefined);

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    fireEvent.click(await screen.findByText("הסר"));

    await waitFor(() => expect(rangesApi.removeRangeAssignment).toHaveBeenCalledWith("event-1", "a1"));
  });
});
*/

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

    await waitFor(() => expect(rangesApi.removeRangeAssignment).toHaveBeenCalledWith("event-refresh", "assignment-refresh"));
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
});
