import { describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({ api: { get: vi.fn() } }));

describe("getSoldierRangeStatus", () => {
  it("calls the soldier-scoped range-status endpoint", async () => {
    const { api } = await import("./client");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { soldier_id: "s1", statuses: [] },
    });
    const { getSoldierRangeStatus } = await import("./rangeStatus");

    const result = await getSoldierRangeStatus("s1");

    expect(api.get).toHaveBeenCalledWith("/soldiers/s1/range-status");
    expect(result).toEqual({ soldier_id: "s1", statuses: [] });
  });

  it("normalizes a malformed statuses field to an empty array", async () => {
    const { api } = await import("./client");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { soldier_id: "s1", statuses: "not-an-array" },
    });
    const { getSoldierRangeStatus } = await import("./rangeStatus");

    const result = await getSoldierRangeStatus("s1");

    expect(result).toEqual({ soldier_id: "s1", statuses: [] });
  });

  it("throws a descriptive error for a malformed top-level response", async () => {
    const { api } = await import("./client");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: [] });
    const { getSoldierRangeStatus } = await import("./rangeStatus");

    await expect(getSoldierRangeStatus("s1")).rejects.toThrow("Invalid range status response");
  });

  it("throws a descriptive error when the required soldier_id field is missing", async () => {
    const { api } = await import("./client");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { statuses: [] } });
    const { getSoldierRangeStatus } = await import("./rangeStatus");

    await expect(getSoldierRangeStatus("s1")).rejects.toThrow("Invalid range status response");
  });
});
