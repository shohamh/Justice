import { describe, it, expect, beforeEach, vi } from "vitest";
import { reportFrontendError } from "./errorReporting";

describe("reportFrontendError rate limiting", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({}));
  });

  it("caps repeated reports of the same fingerprint within the window", () => {
    for (let i = 0; i < 25; i++) {
      reportFrontendError({ kind: "uncaught-error", message: "boom", filename: "x.ts", line: 1 });
    }
    // Default cap is 10 per window (VITE_ERROR_RATE_LIMIT_MAX_PER_WINDOW).
    expect(fetch).toHaveBeenCalledTimes(10);
  });

  it("does not cap a different fingerprint", () => {
    for (let i = 0; i < 15; i++) {
      reportFrontendError({ kind: "uncaught-error", message: "boom-a", filename: "x.ts", line: 1 });
    }
    reportFrontendError({ kind: "uncaught-error", message: "boom-b", filename: "y.ts", line: 2 });
    expect(fetch).toHaveBeenCalledTimes(11);
  });

  it("allows reports again once the window has passed", () => {
    vi.useFakeTimers();
    try {
      for (let i = 0; i < 10; i++) {
        reportFrontendError({ kind: "uncaught-error", message: "boom-c", filename: "z.ts", line: 3 });
      }
      expect(fetch).toHaveBeenCalledTimes(10);

      vi.advanceTimersByTime(61_000);
      reportFrontendError({ kind: "uncaught-error", message: "boom-c", filename: "z.ts", line: 3 });
      expect(fetch).toHaveBeenCalledTimes(11);
    } finally {
      vi.useRealTimers();
    }
  });
});
