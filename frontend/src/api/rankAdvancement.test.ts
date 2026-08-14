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
    { rank: "טוראי", months_to_next: 4 },
    { rank: "רבט", months_to_next: null },
  ],
  officer: [
    { rank: "סגן", months_to_next: 12 },
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

  it("puts the interval updates and returns the updated ladder", async () => {
    mockPut.mockResolvedValueOnce({ data: ladder });
    const { updateRankAdvancementIntervals } = await import("./rankAdvancement");

    const intervals = [
      { track: "enlisted" as const, rank: "רבט", months_to_next: 5 },
    ];
    await expect(updateRankAdvancementIntervals(intervals)).resolves.toEqual(ladder);
    expect(mockPut).toHaveBeenCalledWith("/soldiers/rank-advancement-intervals", intervals);
  });
});
