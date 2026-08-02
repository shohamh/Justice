import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import NotificationBell from "./NotificationBell";
import * as notificationsApi from "../api/notifications";

vi.mock("../api/notifications");

const baseNotification = {
  id: "n1",
  soldier_id: "s1",
  body: null,
  reference_type: null,
  reference_id: null,
  is_read: false,
  created_at: new Date().toISOString(),
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(notificationsApi.getUnreadCount).mockResolvedValue({ count: 2 });
});

describe("NotificationBell icon differentiation", () => {
  it("shows a different icon for system_announcement than for announcement", async () => {
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({
      items: [
        { ...baseNotification, id: "n1", title: "Scoped", type: "announcement" },
        { ...baseNotification, id: "n2", title: "Org wide", type: "system_announcement" },
      ],
      total: 2,
    });
    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    );
    const bellButton = await screen.findByTestId("notification-bell");
    bellButton.click();
    const scopedRow = await screen.findByText("Scoped");
    const orgWideRow = await screen.findByText("Org wide");
    expect(scopedRow.closest("div")?.parentElement?.textContent).toContain("📢");
    expect(orgWideRow.closest("div")?.parentElement?.textContent).toContain("📣");
  });
  it("shows the range lifecycle icon and label", async () => {
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({
      items: [{ ...baseNotification, title: "Range cancelled", type: "range_cancelled" }],
      total: 1,
    });
    render(<MemoryRouter><NotificationBell /></MemoryRouter>);
    (await screen.findByTestId("notification-bell")).click();
    const row = await screen.findByText("Range cancelled");
    expect(row.closest("div")?.parentElement?.textContent).toContain(String.fromCodePoint(0x1f6ab));
    expect(document.querySelector("[aria-label=\"range_cancelled\"]")).toBeTruthy();
  });
});
