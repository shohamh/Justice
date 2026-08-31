import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import {
  exemptionFileDownloadUrl,
  listExemptionRequestsForSoldier,
  listExemptions,
  listMyExemptionRequests,
  listPendingExemptionRequests,
  type ExemptionRequest,
} from "./exemptions";

vi.mock("./client");

function makeExemptionRequest(): ExemptionRequest {
  return {
    id: "request-1",
    soldier_id: "soldier-1",
    soldier_name: "Soldier One",
    node_name: "Unit A",
    exemption_type_id: "type-1",
    start_date: "2026-08-20",
    end_date: null,
    reason: "Medical",
    status: "pending_commander",
    commander_approved_by: null,
    commander_approved_at: null,
    commander_approval_note: null,
    waiting_on: null,
    decided_by: null,
    decided_at: null,
    requested_at: "2026-08-20T00:00:00Z",
    updated_at: "2026-08-20T00:00:00Z",
    decision_note: null,
    created_at: "2026-08-20T00:00:00Z",
    files: [],
    nearest_commander: { id: "commander-1", name: "Commander One" },
    nearest_duty_manager: { id: "manager-1", name: "Manager One" },
    can_approve_commander_step: true,
    can_approve_duty_manager_step: false,
  };
}

describe("exemptionFileDownloadUrl", () => {
  it("returns a path relative to the api client's baseURL, without a duplicate /api prefix", () => {
    expect(exemptionFileDownloadUrl("req-1", "file-1")).toBe("/exemption-requests/req-1/files/file-1");
  });
});

describe("listPendingExemptionRequests", () => {
  it("rejects a malformed pending exemption requests payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listPendingExemptionRequests()).rejects.toThrow(
      "Invalid pending exemption requests response",
    );
  });

  it("returns an equivalent pending exemption requests array when the payload is valid", async () => {
    const payload = [makeExemptionRequest()];
    vi.mocked(api.get).mockResolvedValue({ data: payload });

    await expect(listPendingExemptionRequests()).resolves.toEqual(payload);
  });

  it("drops a non-object row and normalizes a row's malformed files field to []", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [42, { ...makeExemptionRequest(), files: "not-an-array" }],
    });

    const result = await listPendingExemptionRequests();

    expect(result).toHaveLength(1);
    expect(result[0].files).toEqual([]);
  });
});

describe("optional exemption list adapters", () => {
  it.each([
    ["listExemptions", () => listExemptions("soldier-1")],
    ["listMyExemptionRequests", () => listMyExemptionRequests()],
    ["listExemptionRequestsForSoldier", () => listExemptionRequestsForSoldier("soldier-1")],
  ])("returns an empty list when %s receives a non-array payload", async (_name, call) => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(call()).resolves.toEqual([]);
  });

  it("normalizes a malformed files field on a listMyExemptionRequests row to []", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [{ ...makeExemptionRequest(), files: null }],
    });

    const result = await listMyExemptionRequests();

    expect(result[0].files).toEqual([]);
  });
});
