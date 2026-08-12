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
});
