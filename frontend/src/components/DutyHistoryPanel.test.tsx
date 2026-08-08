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
});
