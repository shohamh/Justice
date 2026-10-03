import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { getExchangeSyncSummary, listExchangeSyncEvents, retryExchangeSyncEvent } from "./exchangeCalendarSync";

vi.mock("./client", () => ({ api: { get: vi.fn(), post: vi.fn() } }));

describe("Exchange calendar admin API", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
  });

  it("reads counts and keeps worker heartbeat distinct from Exchange reachability", async () => {
    const summary = {
      counts: { eligible: 8, queued: 1, in_progress: 1, synced: 3, partial: 1, retry_wait: 1, failed: 1 },
      recent: { created: 2, updated: 1, cancelled: 1, partial: 1, failed: 1 },
      worker_heartbeat_at: "2026-09-29T09:00:00Z", last_probe_at: "2026-09-29T08:50:00Z",
      exchange_reachable: false, last_connection_attempt_at: "2026-09-29T08:50:00Z",
      last_successful_contact_at: "2026-09-29T08:00:00Z",
      latest_connection_error: "Calendar sync failed.", global_backoff_until: "2026-09-29T09:10:00Z",
    };
    vi.mocked(api.get).mockResolvedValue({ data: summary });
    expect(await getExchangeSyncSummary()).toEqual(summary);
    expect(api.get).toHaveBeenCalledWith("/admin/exchange-calendar-sync/summary");
  });

  it("requests a bounded events page and preserves sanitized attempt history", async () => {
    const page = { total: 1, limit: 25, offset: 0, items: [{
      source_type: "duty_shift", source_id: "source-1", source_date: "2026-10-01", status: "partial",
      last_attempt_at: "2026-09-29T09:00:00Z", last_success_at: "2026-09-29T09:00:00Z",
      error_category: "missing_email", error: "An invited person has no usable email address.",
      current_projection_problems: [{ code: "missing_email", message: "An invited person has no usable email address." }],
      recent_attempts: [{ outcome: "partial", attempted_at: "2026-09-29T09:00:00Z", error_category: "missing_email", error: "An invited person has no usable email address." }],
    }] };
    vi.mocked(api.get).mockResolvedValue({ data: page });
    expect(await listExchangeSyncEvents(25, 0)).toEqual(page);
    expect(api.get).toHaveBeenCalledWith("/admin/exchange-calendar-sync/events", { params: { limit: 25, offset: 0 } });
  });

  it("posts only a source key for asynchronous retry", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: "accepted" } });
    expect(await retryExchangeSyncEvent("range_event", "source-2")).toEqual({ status: "accepted" });
    expect(api.post).toHaveBeenCalledWith("/admin/exchange-calendar-sync/events/range_event/source-2/retry");
  });
});
