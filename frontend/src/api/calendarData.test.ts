import { describe, expect, it } from "vitest";

import { loadCalendarData } from "./calendarData";

describe("loadCalendarData", () => {
  it("keeps the calendar when the optional ranges request fails", async () => {
    const calendar = { shifts: [{ id: "shift-1" }] };

    await expect(
      loadCalendarData(
        () => Promise.resolve(calendar),
        () => Promise.reject(new Error("ranges unavailable")),
        true,
      ),
    ).resolves.toEqual({ calendar, ranges: [] });
  });
});
