import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "./client";
import { listIdentityConflicts, resolveIdentityConflict, dismissIdentityConflict } from "./identityConflicts";

vi.mock("./client", () => ({ api: { get: vi.fn(), post: vi.fn() } }));

const conflict = {
  id: "c1", source: "sso", status: "open", ad_username: "dude", personal_number: null,
  created_at: "2026-10-02T10:00:00Z", resolved_at: null, chosen_soldier_id: null, resolution_note: null,
  candidates: [{ soldier_id: "s1", full_name: "A", personal_number: "111", email_masked: "d***@x.co", matched_fields: ["email"], active: true }],
};

describe("identityConflicts api", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
  });

  it("lists conflicts for a status", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [conflict] } });
    const res = await listIdentityConflicts("open");
    expect(api.get).toHaveBeenCalledWith("/admin/identity-conflicts", { params: { status: "open" } });
    expect(res.items).toHaveLength(1);
    expect(res.items[0].candidates[0].soldier_id).toBe("s1");
  });

  it("tolerates a malformed items field and rejects a non-object body", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: "nope" } });
    expect((await listIdentityConflicts()).items).toEqual([]);
    vi.mocked(api.get).mockResolvedValue({ data: null });
    await expect(listIdentityConflicts()).rejects.toThrow();
  });

  it("resolves with the chosen soldier id", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { ...conflict, status: "resolved" } });
    const res = await resolveIdentityConflict("c1", "s1");
    expect(api.post).toHaveBeenCalledWith("/admin/identity-conflicts/c1/resolve", { soldier_id: "s1" });
    expect(res.status).toBe("resolved");
  });

  it("dismisses with a reason", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { ...conflict, status: "dismissed" } });
    await dismissIdentityConflict("c1", "duplicate");
    expect(api.post).toHaveBeenCalledWith("/admin/identity-conflicts/c1/dismiss", { reason: "duplicate" });
  });
});
