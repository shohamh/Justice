import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ExchangeCalendarSyncContent from "./ExchangeCalendarSyncContent";
import { ADMIN_SETTINGS_TAB_ORDER } from "./AdminSettingsPage";
import * as syncApi from "../../api/exchangeCalendarSync";

vi.mock("../../api/exchangeCalendarSync");

const summary = {
  counts: { eligible: 8, queued: 1, in_progress: 1, synced: 3, partial: 1, retry_wait: 1, failed: 1 },
  recent: { created: 2, updated: 1, cancelled: 1, partial: 1, failed: 1 },
  worker_heartbeat_at: "2026-09-29T09:00:00Z", last_probe_at: "2026-09-29T08:50:00Z",
  exchange_reachable: false, last_connection_attempt_at: "2026-09-29T08:50:00Z",
  last_successful_contact_at: "2026-09-29T08:00:00Z",
  latest_connection_error: "Exchange is unavailable. The worker will retry.",
  global_backoff_until: "2026-09-29T09:10:00Z",
};

const event = {
  source_type: "duty_shift" as const, source_id: "source-1", source_date: "2026-10-01",
  status: "partial" as const, last_attempt_at: "2026-09-29T09:00:00Z",
  last_success_at: "2026-09-29T09:00:00Z", error_category: "missing_email",
  error: "An invited person has no usable email address.",
  current_projection_problems: [{ code: "missing_email", message: "An invited person has no usable email address." }],
  recent_attempts: [{ outcome: "partial", attempted_at: "2026-09-29T09:00:00Z", error_category: "missing_email", error: "An invited person has no usable email address." }],
};

function renderContent() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><ExchangeCalendarSyncContent /></QueryClientProvider>);
}

describe("ExchangeCalendarSyncContent", () => {
  beforeEach(() => {
    vi.mocked(syncApi.getExchangeSyncSummary).mockReset().mockResolvedValue(summary);
    vi.mocked(syncApi.listExchangeSyncEvents).mockReset().mockResolvedValue({ items: [event], total: 1, limit: 25, offset: 0 });
    vi.mocked(syncApi.retryExchangeSyncEvent).mockReset().mockResolvedValue({ status: "accepted" });
  });

  it("is mounted after HR sync in the admin settings tabs", () => {
    expect(ADMIN_SETTINGS_TAB_ORDER.at(-1)).toBe("exchange-calendar-sync");
  });

  it("shows counts, separate worker and Exchange state, outage and shared backoff", async () => {
    renderContent();
    await screen.findByTestId("exchange-sync-summary");
    expect(screen.getByTestId("exchange-sync-count-synced")).toHaveTextContent("3");
    expect(screen.getByTestId("exchange-sync-count-eligible")).toHaveTextContent("8");
    expect(screen.getByTestId("exchange-sync-recent-created")).toHaveTextContent("2");
    expect(screen.getByTestId("exchange-sync-worker")).toHaveTextContent("2026");
    expect(screen.getByTestId("exchange-sync-connection")).toHaveTextContent("Exchange");
    expect(screen.getByTestId("exchange-sync-backoff")).toHaveTextContent("2026");
  });

  it("shows partial attendee problems and recent attempt history", async () => {
    renderContent();
    const row = (await screen.findByTestId("exchange-sync-event-source-1")).closest("tr");
    expect(row).not.toBeNull();
    expect(row).toHaveTextContent("partial");
    expect(row).toHaveTextContent("An invited person has no usable email address.");
    fireEvent.click(screen.getByTestId("exchange-sync-history-source-1"));
    expect(await screen.findByTestId("exchange-sync-history-detail")).toHaveTextContent("partial");
  });

  it("handles loading, empty events and query errors", async () => {
    vi.mocked(syncApi.listExchangeSyncEvents).mockImplementation(() => new Promise(() => {}));
    renderContent();
    expect(screen.getByTestId("exchange-sync-events-loading")).toBeInTheDocument();
  });

  it("shows an empty table after loading", async () => {
    vi.mocked(syncApi.listExchangeSyncEvents).mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
    renderContent();
    expect(await screen.findByTestId("exchange-sync-events-empty")).toBeInTheDocument();
  });

  it("shows a load error when summary or events fail", async () => {
    vi.mocked(syncApi.getExchangeSyncSummary).mockRejectedValue(new Error("offline"));
    vi.mocked(syncApi.listExchangeSyncEvents).mockRejectedValue(new Error("offline"));
    renderContent();
    expect(await screen.findByTestId("exchange-sync-summary-error")).toBeInTheDocument();
    expect(await screen.findByTestId("exchange-sync-events-error")).toBeInTheDocument();
  });

  it("confirms a retry and reports accepted queueing without claiming sync", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderContent();
    await screen.findByTestId("exchange-sync-event-source-1");
    fireEvent.click(screen.getByTestId("exchange-sync-retry-source-1"));
    await waitFor(() => expect(syncApi.retryExchangeSyncEvent).toHaveBeenCalledWith("duty_shift", "source-1"));
    expect(await screen.findByTestId("exchange-sync-retry-result")).toHaveTextContent("queued");
    confirm.mockRestore();
  });
});
