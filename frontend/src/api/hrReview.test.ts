import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "./client";
import {
  listHeldForReview,
  listDivergences,
  listVanished,
  listRankConflicts,
  listSyncRuns,
  dismissHeldForReview,
  clearFieldOverride,
  runSyncNow,
  listHrIdentityConflicts,
  acknowledgeHrIdentityConflict,
  chooseHrIdentityCandidate,
  listHrPreferredRecords,
  clearHrPreferredRecord,
} from "./hrReview";

vi.mock("./client", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

describe("hrReview api", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.delete).mockReset();
  });

  it("listHeldForReview parses items", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        items: [{
          id: "1", personal_number: "123", review_reason: "bad date", last_synced_at: null,
          raw_dto: { rank: "bad-value" },
        }],
      },
    });
    const result = await listHeldForReview();
    expect(api.get).toHaveBeenCalledWith("/admin/hr-sync/held-for-review");
    expect(result.items).toHaveLength(1);
    expect(result.items[0].personal_number).toBe("123");
    expect(result.items[0].raw_dto).toEqual({ rank: "bad-value" });
  });

  it("dismissHeldForReview posts to the right path", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { id: "1", personal_number: "123", review_reason: "bad date", last_synced_at: null },
    });
    await dismissHeldForReview("1");
    expect(api.post).toHaveBeenCalledWith("/admin/hr-sync/held-for-review/1/dismiss");
  });

  it("listDivergences parses items", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        items: [{
          id: "1", soldier_hr_profile_id: "2",
          soldier_full_name: "ישראל ישראלי", soldier_personal_number: "1234567",
          field_name: "phone",
          hr_value: "050-1", local_value: "050-2", created_at: "2026-01-01T00:00:00Z",
        }],
      },
    });
    const result = await listDivergences();
    expect(result.items[0].field_name).toBe("phone");
    expect(result.items[0].soldier_full_name).toBe("ישראל ישראלי");
  });

  it("clearFieldOverride posts field_name in the body", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { id: "1", personal_number: "123", review_reason: null, last_synced_at: null },
    });
    await clearFieldOverride("1", "phone");
    expect(api.post).toHaveBeenCalledWith("/admin/hr-sync/divergences/1/clear-override", { field_name: "phone" });
  });

  it("listVanished parses items", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [{ id: "1", personal_number: "123", last_synced_at: null }] },
    });
    const result = await listVanished();
    expect(result.items).toHaveLength(1);
  });

  it("listRankConflicts parses items", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        items: [{
          id: "1", soldier_id: "2",
          soldier_full_name: "ישראל ישראלי", soldier_personal_number: "1234567",
          old_rank: "טוראי", new_rank: "סמל",
          triggered_by_worker_decision: true, non_sequential_jump: false,
          created_at: "2026-01-01T00:00:00Z",
        }],
      },
    });
    const result = await listRankConflicts();
    expect(result.items[0].old_rank).toBe("טוראי");
    expect(result.items[0].soldier_full_name).toBe("ישראל ישראלי");
  });

  it("listSyncRuns parses both run lists", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { person_syncs: [], hierarchy_syncs: [] },
    });
    const result = await listSyncRuns();
    expect(result.person_syncs).toEqual([]);
    expect(result.hierarchy_syncs).toEqual([]);
  });

  it("runSyncNow posts with no body", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { hierarchy_sync_id: "1", person_sync_id: "2" },
    });
    const result = await runSyncNow();
    expect(api.post).toHaveBeenCalledWith("/admin/hr-sync/run-now");
    expect(result.person_sync_id).toBe("2");
  });

  it("listHrIdentityConflicts passes the status filter and normalizes nested lists", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [{ id: "c1", personal_number: "123", candidates: "bad", colliding_soldiers: null, preferred_record: undefined }] },
    });
    const res = await listHrIdentityConflicts("all");
    expect(api.get).toHaveBeenCalledWith("/admin/hr-sync/identity-conflicts", { params: { status: "all" } });
    expect(res.items[0].candidates).toEqual([]);
    expect(res.items[0].colliding_soldiers).toEqual([]);
    expect(res.items[0].preferred_record).toBeNull();
  });

  it("acknowledge posts without a body", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { id: "c1", status: "acknowledged", candidates: [] } });
    const res = await acknowledgeHrIdentityConflict("c1");
    expect(api.post).toHaveBeenCalledWith("/admin/hr-sync/identity-conflicts/c1/acknowledge");
    expect(res.status).toBe("acknowledged");
  });

  it("choose posts the candidate index", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { id: "c1", status: "resolved", candidates: [] } });
    await chooseHrIdentityCandidate("c1", 0);
    expect(api.post).toHaveBeenCalledWith("/admin/hr-sync/identity-conflicts/c1/choose", { candidate_index: 0 });
  });

  it("lists and clears preferred records", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [{ personal_number: "123", key_type: "username", key_value: "u", chosen_by: null, chosen_by_name: null, chosen_at: "x" }] } });
    expect((await listHrPreferredRecords()).items).toHaveLength(1);
    vi.mocked(api.delete).mockResolvedValue({});
    await clearHrPreferredRecord("1/2");
    expect(api.delete).toHaveBeenCalledWith("/admin/hr-sync/preferred-records/1%2F2");
  });
});
