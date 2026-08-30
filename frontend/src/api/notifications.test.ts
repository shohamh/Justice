import { describe, it, expect, vi } from "vitest";
import { api } from "./client";
import {
  getNotificationLink,
  getPreferences,
  getUnreadCount,
  listCommanderScopes,
  listNotifications,
  updatePreferences,
} from "./notifications";

vi.mock("./client");

describe("getNotificationLink", () => {
  it("routes swap_offer_incoming to the incoming tab", () => {
    const link = getNotificationLink({ type: "swap_offer_incoming", reference_type: "swap_request", reference_id: "r1" });
    expect(link).toBe("/swaps?tab=incoming");
  });

  it("routes swap_pending_approval to the approvals swaps tab", () => {
    const link = getNotificationLink({ type: "swap_pending_approval", reference_type: "swap_request", reference_id: "r1" });
    expect(link).toBe("/approvals?tab=swaps");
  });

  it("routes constraint_pending to the approvals constraints tab", () => {
    const link = getNotificationLink({ type: "constraint_pending", reference_type: "personal_constraint", reference_id: "r1" });
    expect(link).toBe("/approvals?tab=constraints");
  });

  it("routes constraint_approved (same reference_type) to my-requests", () => {
    const link = getNotificationLink({ type: "constraint_approved", reference_type: "personal_constraint", reference_id: "r1" });
    expect(link).toBe("/my-requests");
  });

  it("routes exemption_request_pending to the tab named in metadata.target_tab", () => {
    const link = getNotificationLink({
      type: "exemption_request_pending", reference_type: "exemption_request", reference_id: "r1",
      metadata: { target_tab: "waiting" },
    });
    expect(link).toBe("/approvals?tab=waiting");
  });

  it("defaults exemption_request_pending to the exemptions tab when metadata is absent", () => {
    const link = getNotificationLink({ type: "exemption_request_pending", reference_type: "exemption_request", reference_id: "r1" });
    expect(link).toBe("/approvals?tab=exemptions");
  });

  it("routes exemption_approved (same reference_type) to my-requests", () => {
    const link = getNotificationLink({ type: "exemption_approved", reference_type: "exemption_request", reference_id: "r1" });
    expect(link).toBe("/my-requests");
  });

  it("routes transfer_request_pending to the approvals transfers tab", () => {
    const link = getNotificationLink({ type: "transfer_request_pending", reference_type: "hierarchy_transfer_request", reference_id: "r1" });
    expect(link).toBe("/approvals?tab=transfers");
  });

  it("does not link transfer_request_rejected (no soldier-facing status page exists)", () => {
    const link = getNotificationLink({ type: "transfer_request_rejected", reference_type: "hierarchy_transfer_request", reference_id: "r1" });
    expect(link).toBeNull();
  });

  it("routes enrollment_request_received to the approvals enrollment tab", () => {
    const link = getNotificationLink({ type: "enrollment_request_received", reference_type: "enrollment_request", reference_id: "r1" });
    expect(link).toBe("/approvals?tab=enrollment");
  });

  it("routes algorithm_job links through the working /planning/shifts redirect target", () => {
    const link = getNotificationLink({ type: "algorithm_job_done", reference_type: "algorithm_job", reference_id: "job1" });
    expect(link).toBe("/planning/shifts?jobId=job1");
  });

  it("routes score_adjusted to the profile page", () => {
    const link = getNotificationLink({ type: "score_adjusted", reference_type: "score_adjustment", reference_id: "r1" });
    expect(link).toBe("/profile");
  });

  it("routes gimelim_* notifications to my-duties", () => {
    const link = getNotificationLink({ type: "gimelim_reserve_called_up", reference_type: "duty_shift", reference_id: "r1" });
    expect(link).toBe("/my-duties");
  });

  it.each(["rank_advanced", "rank_advancement_soon", "mitvahim_expiring_soon", "mitvahim_expired", "alal_expiring_soon", "alal_expired"])(
    "routes %s (no reference_type) to the profile page",
    (type) => {
      const link = getNotificationLink({ type, reference_type: null, reference_id: null });
      expect(link).toBe("/profile");
    },
  );

  it("returns null for types with no known destination", () => {
    const link = getNotificationLink({ type: "exemption_revoked", reference_type: "soldier_exemption", reference_id: "r1" });
    expect(link).toBeNull();
  });
});

describe("notification APIs", () => {
  it("rejects a malformed unread count payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { count: "2" } });

    await expect(getUnreadCount()).rejects.toThrow("Invalid unread notifications response");
  });

  it("rejects a malformed notifications page payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: { detail: "unexpected response" }, total: 1 } });

    await expect(listNotifications()).rejects.toThrow("Invalid notifications response");
  });

  it.each([
    ["getPreferences", () => getPreferences()],
    ["updatePreferences", () => updatePreferences([])],
    ["listCommanderScopes", () => listCommanderScopes()],
  ])("returns an empty list when %s receives a non-array payload", async (_name, call) => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });
    vi.mocked(api.put).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(call()).resolves.toEqual([]);
  });
});
