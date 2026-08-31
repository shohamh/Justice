import { describe, it, expect, vi } from "vitest";

const mockGet = vi.fn();
vi.mock("./client", () => ({
  api: {
    get: (...args: unknown[]) => mockGet(...args),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("calendarHolidays api", () => {
  it("listHolidays returns the array on a valid response", async () => {
    mockGet.mockResolvedValue({ data: [{ date: "2026-09-12", name: "Rosh Hashanah" }] });
    const { listHolidays } = await import("./calendarHolidays");
    const result = await listHolidays(2026);
    expect(result).toEqual([{ date: "2026-09-12", name: "Rosh Hashanah" }]);
  });

  it("listHolidays normalizes a malformed (non-array) response to an empty list", async () => {
    mockGet.mockResolvedValue({ data: { not: "an array" } });
    const { listHolidays } = await import("./calendarHolidays");
    const result = await listHolidays(2026);
    expect(result).toEqual([]);
  });
});
