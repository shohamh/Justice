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

  it("starts the optional ranges request before the calendar request resolves", async () => {
    let resolveCalendar!: (value: { shifts: { id: string }[] }) => void;
    let rangesStarted = false;
    const calendarPromise = new Promise<{ shifts: { id: string }[] }>((resolve) => {
      resolveCalendar = resolve;
    });

    const resultPromise = loadCalendarData(
      () => calendarPromise,
      async () => {
        rangesStarted = true;
        return [];
      },
      true,
    );

    expect(rangesStarted).toBe(true);
    resolveCalendar({ shifts: [] });
    await expect(resultPromise).resolves.toEqual({ calendar: { shifts: [] }, ranges: [] });
  });
});
