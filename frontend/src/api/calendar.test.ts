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

describe("calendar api", () => {
  describe("getCalendarShifts", () => {
    it("returns shifts with assignees/crossed_holidays intact on a valid response", async () => {
      const shift = {
        id: "shift-1",
        duty_type_id: "dt-1",
        assignees: [{ assignment_id: "a-1" }],
        crossed_holidays: [{ date: "2026-09-12", name: "Rosh Hashanah" }],
      };
      mockGet.mockResolvedValue({ data: { shifts: [shift] } });
      const { getCalendarShifts } = await import("./calendar");
      const result = await getCalendarShifts({ nodeId: "node-1" });
      expect(result.shifts).toHaveLength(1);
      expect(result.shifts[0].assignees).toEqual([{ assignment_id: "a-1" }]);
      expect(result.shifts[0].crossed_holidays).toEqual([{ date: "2026-09-12", name: "Rosh Hashanah" }]);
    });

    it("throws a descriptive error for a malformed top-level response", async () => {
      mockGet.mockResolvedValue({ data: [] });
      const { getCalendarShifts } = await import("./calendar");
      await expect(getCalendarShifts({ nodeId: "node-1" })).rejects.toThrow("Invalid calendar shifts response");
    });

    it("normalizes a malformed shifts field to an empty array", async () => {
      mockGet.mockResolvedValue({ data: { shifts: "not-an-array" } });
      const { getCalendarShifts } = await import("./calendar");
      const result = await getCalendarShifts({ nodeId: "node-1" });
      expect(result.shifts).toEqual([]);
    });

    it("normalizes a malformed assignees/crossed_holidays field on an individual shift without dropping the shift", async () => {
      mockGet.mockResolvedValue({
        data: { shifts: [{ id: "shift-1", assignees: "bad", crossed_holidays: null }] },
      });
      const { getCalendarShifts } = await import("./calendar");
      const result = await getCalendarShifts({ nodeId: "node-1" });
      expect(result.shifts).toHaveLength(1);
      expect(result.shifts[0].id).toBe("shift-1");
      expect(result.shifts[0].assignees).toEqual([]);
      expect(result.shifts[0].crossed_holidays).toEqual([]);
    });

    it("drops a completely malformed (non-object) shift entry to an empty-normalized shift", async () => {
      mockGet.mockResolvedValue({ data: { shifts: ["not-an-object"] } });
      const { getCalendarShifts } = await import("./calendar");
      const result = await getCalendarShifts({ nodeId: "node-1" });
      expect(result.shifts).toHaveLength(1);
      expect(result.shifts[0].assignees).toEqual([]);
      expect(result.shifts[0].crossed_holidays).toEqual([]);
    });
  });

  describe("getCalendarShift", () => {
    it("returns a shift with assignees/crossed_holidays intact on a valid response", async () => {
      const shift = {
        id: "shift-1",
        duty_type_id: "dt-1",
        assignees: [{ assignment_id: "a-1" }],
        crossed_holidays: [{ date: "2026-09-12", name: "Rosh Hashanah" }],
      };
      mockGet.mockResolvedValue({ data: shift });
      const { getCalendarShift } = await import("./calendar");
      const result = await getCalendarShift("shift-1");
      expect(result.assignees).toEqual([{ assignment_id: "a-1" }]);
      expect(result.crossed_holidays).toEqual([{ date: "2026-09-12", name: "Rosh Hashanah" }]);
    });

    it("normalizes a malformed assignees/crossed_holidays field to an empty array", async () => {
      mockGet.mockResolvedValue({ data: { id: "shift-1", assignees: "bad", crossed_holidays: null } });
      const { getCalendarShift } = await import("./calendar");
      const result = await getCalendarShift("shift-1");
      expect(result.id).toBe("shift-1");
      expect(result.assignees).toEqual([]);
      expect(result.crossed_holidays).toEqual([]);
    });

    it("normalizes a completely malformed (non-object) response to an empty-normalized shift", async () => {
      mockGet.mockResolvedValue({ data: "not-an-object" });
      const { getCalendarShift } = await import("./calendar");
      const result = await getCalendarShift("shift-1");
      expect(result.assignees).toEqual([]);
      expect(result.crossed_holidays).toEqual([]);
    });
  });

  describe("getUnitCalendar", () => {
    it("normalizes a malformed (non-array) response to an empty list", async () => {
      mockGet.mockResolvedValue({ data: { not: "an array" } });
      const { getUnitCalendar } = await import("./calendar");
      const result = await getUnitCalendar("node-1");
      expect(result).toEqual([]);
    });
  });
});
