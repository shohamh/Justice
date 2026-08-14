import { afterEach, describe, expect, it, vi } from "vitest";

const mockGet = vi.fn();
const mockPut = vi.fn();

vi.mock("./client", () => ({
  api: {
    get: (...args: unknown[]) => mockGet(...args),
    put: (...args: unknown[]) => mockPut(...args),
  },
}));

const ladder = {
  enlisted: [
    { rank: "טוראי", months_to_next: 4, advance_on_career_entry: false },
    { rank: "רבט", months_to_next: null, advance_on_career_entry: false },
  ],
  officer: [
    { rank: "סגן", months_to_next: 12, advance_on_career_entry: false },
  ],
  officer_academic: [
    { rank: "קאב", months_to_next: 12, advance_on_career_entry: true },
  ],
};

describe("rank advancement api", () => {
  afterEach(() => {
    mockGet.mockReset();
    mockPut.mockReset();
  });

  it("gets the rank ladder from the rank-ladder endpoint", async () => {
    mockGet.mockResolvedValueOnce({ data: ladder });
    const { getRankLadder } = await import("./rankAdvancement");

    await expect(getRankLadder()).resolves.toEqual(ladder);
    expect(mockGet).toHaveBeenCalledWith("/soldiers/rank-ladder");
  });

  it("gets the public rank ladder from the unauthenticated auth endpoint", async () => {
    mockGet.mockResolvedValueOnce({ data: ladder });
    const { getPublicRankLadder } = await import("./rankAdvancement");

    await expect(getPublicRankLadder()).resolves.toEqual(ladder);
    expect(mockGet).toHaveBeenCalledWith("/auth/rank-ladder");
  });

  it("puts the interval updates and returns the updated ladder", async () => {
    mockPut.mockResolvedValueOnce({ data: ladder });
    const { updateRankAdvancementIntervals } = await import("./rankAdvancement");

    const intervals = [
      { track: "enlisted" as const, rank: "רבט", months_to_next: 5, advance_on_career_entry: false },
    ];
    await expect(updateRankAdvancementIntervals(intervals)).resolves.toEqual(ladder);
    expect(mockPut).toHaveBeenCalledWith("/soldiers/rank-advancement-intervals", intervals);
  });

  it("getRankLadder response includes officer_academic and advance_on_career_entry", async () => {
    mockGet.mockResolvedValueOnce({ data: ladder });
    const { getRankLadder } = await import("./rankAdvancement");

    const result = await getRankLadder();
    expect(result.officer_academic).toBeDefined();
    expect(result.officer_academic[0].advance_on_career_entry).toBe(true);
  });
});
