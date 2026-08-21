// frontend/src/components/DutyHistoryPanel.test.tsx
import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import DutyHistoryPanel from "./DutyHistoryPanel";
import * as dutyHistoryApi from "../api/dutyHistory";

vi.mock("../api/dutyHistory");
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { id: "u-manager" } }) }));
vi.mock("../api/dutyConfig", () => ({ listDutyTypes: () => Promise.resolve([]) }));
const mockT = (k: string) => k;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: mockT }) }));

describe("DutyHistoryPanel range events", () => {
  it("renders a range_assignment event with its status", async () => {
    vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue([
      {
        id: "r1", event_type: "range_assignment", date: "2026-09-01", end_date: null,
        title: "מטווח laser במטווח צפון", description: null, status: "present",
        metadata: { range_type: "laser", location_name: "מטווח צפון", is_reserve: "false", was_promoted_from_reserve: "false" },
        created_at: "2026-08-01T00:00:00Z",
      },
    ]);
    render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} />);
    expect(await screen.findByTestId("history-event-range_assignment")).toBeTruthy();
  });

  it("renders a range_removed event with its reason", async () => {
    vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue([
      {
        id: "r2", event_type: "range_removed", date: "2026-09-01", end_date: null,
        title: "הוסר ממטווח laser במטווח צפון", description: "חופשה", status: null,
        metadata: { range_type: "laser", location_name: "מטווח צפון", source: "excusal" },
        created_at: "2026-08-01T00:00:00Z",
      },
    ]);
    render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} />);
    const el = await screen.findByTestId("history-event-range_removed");
    expect(el.textContent).toContain("חופשה");
  });

  it("does not duplicate the removal reason when a range_removed card is expanded", async () => {
    vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue([
      {
        id: "r3", event_type: "range_removed", date: "2026-09-01", end_date: null,
        title: "הוסר ממטווח laser במטווח צפון", description: "חופשה", status: null,
        metadata: { range_type: "laser", location_name: "מטווח צפון", source: "excusal" },
        created_at: "2026-08-01T00:00:00Z",
      },
    ]);
    render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} />);
    const el = await screen.findByTestId("history-event-range_removed");
    expect(within(el).getAllByText("חופשה")).toHaveLength(1);

    // The click-to-toggle handler is on the inner card div (data-testid wraps
    // both the timeline dot and the card), so click the title text within it.
    fireEvent.click(within(el).getByText("הוסר ממטווח laser במטווח צפון"));

    expect(within(el).getAllByText("חופשה")).toHaveLength(1);
  });

  it("shows who removed the soldier when removed_by_name is present", async () => {
    vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue([
      {
        id: "r4", event_type: "range_removed", date: "2026-09-01", end_date: null,
        title: "הוסר ממטווח laser במטווח צפון", description: "חופשה", status: null,
        metadata: { range_type: "laser", location_name: "מטווח צפון", source: "manual_removal", removed_by_name: "דני כהן" },
        created_at: "2026-08-01T00:00:00Z",
      },
    ]);
    render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} />);
    const el = await screen.findByTestId("history-event-range_removed");
    expect(el.textContent).toContain("דני כהן");
  });

  it("renders the promoted-from-reserve badge on a range_assignment event", async () => {
    vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue([
      {
        id: "r5", event_type: "range_assignment", date: "2026-09-01", end_date: null,
        title: "מטווח laser במטווח צפון", description: null, status: "present",
        metadata: { range_type: "laser", location_name: "מטווח צפון", is_reserve: "false", was_promoted_from_reserve: "true" },
        created_at: "2026-08-01T00:00:00Z",
      },
    ]);
    render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} />);
    const el = await screen.findByTestId("history-event-range_assignment");
    expect(within(el).getByText("קודם מרזרבה")).toBeTruthy();
  });

  it("does not render the promoted-from-reserve badge when false", async () => {
    vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue([
      {
        id: "r6", event_type: "range_assignment", date: "2026-09-01", end_date: null,
        title: "מטווח laser במטווח צפון", description: null, status: "present",
        metadata: { range_type: "laser", location_name: "מטווח צפון", is_reserve: "false", was_promoted_from_reserve: "false" },
        created_at: "2026-08-01T00:00:00Z",
      },
    ]);
    render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} />);
    const el = await screen.findByTestId("history-event-range_assignment");
    expect(within(el).queryByText("קודם מרזרבה")).toBeNull();
  });
});

describe("DutyHistoryPanel event-type filter", () => {
  function threeEvents() {
    return [
      {
        id: "ra1", event_type: "range_assignment", date: "2026-09-01", end_date: null,
        title: "מטווח laser במטווח צפון", description: null, status: "present",
        metadata: { range_type: "laser", location_name: "מטווח צפון", is_reserve: "false", was_promoted_from_reserve: "false" },
        created_at: "2026-08-01T00:00:00Z",
      },
      {
        id: "rr1", event_type: "range_removed", date: "2026-09-02", end_date: null,
        title: "הוסר ממטווח laser במטווח צפון", description: "חופשה", status: null,
        metadata: { range_type: "laser", location_name: "מטווח צפון", source: "excusal" },
        created_at: "2026-08-01T00:00:00Z",
      },
      {
        id: "a1", event_type: "assignment", date: "2026-09-03", end_date: "2026-09-04",
        title: "שמירה במוצב", description: null, status: "published",
        metadata: {},
        created_at: "2026-08-01T00:00:00Z",
      },
    ];
  }

  it("selecting only the 'range' checkbox shows both range_assignment and range_removed events, and hides assignment", async () => {
    vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue(threeEvents());
    render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} />);
    await screen.findByTestId("history-event-range_assignment");

    // Open the dropdown, clear the default "all selected" state, then pick just "range".
    fireEvent.click(screen.getByText("duty_history.filter_types_label"));
    fireEvent.click(screen.getByText("הכל"));
    fireEvent.click(screen.getByText("duty_history.filter_ranges"));

    expect(screen.getByTestId("history-event-range_assignment")).toBeTruthy();
    expect(screen.getByTestId("history-event-range_removed")).toBeTruthy();
    expect(screen.queryByTestId("history-event-assignment")).toBeNull();
  });

  it("initialTypes seeds the filter on mount without needing to open the dropdown", async () => {
    vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue(threeEvents());
    render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} initialTypes={["assignment"]} />);

    await screen.findByTestId("history-event-assignment");
    expect(screen.queryByTestId("history-event-range_assignment")).toBeNull();
    expect(screen.queryByTestId("history-event-range_removed")).toBeNull();
  });
});
