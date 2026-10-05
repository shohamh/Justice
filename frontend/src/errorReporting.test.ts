import { describe, it, expect, beforeEach, vi } from "vitest";
import { AxiosError, type AxiosResponse } from "axios";
import { installGlobalErrorReporting, reportAxiosError, reportFrontendError, setErrorReportingToken } from "./errorReporting";

describe("reportFrontendError rate limiting", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({}));
    setErrorReportingToken(null);
  });

  it("sends the current access token with frontend error reports", () => {
    setErrorReportingToken("access-token");

    reportFrontendError({ kind: "uncaught-error", message: "boom" });

    expect(fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
      headers: expect.objectContaining({ "Content-Type": "application/json", Authorization: "Bearer access-token" }),
    }));
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

describe("frontend telemetry URLs", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({}));
    setErrorReportingToken(null);
  });

  it("sends only request and browser paths for HTTP-500 reports", () => {
    const originalUrl = window.location.href;
    window.history.replaceState({}, "", "/reset-password?token=secret-token#fragment-secret");
    try {
      const error = new AxiosError("HTTP 500");
      error.response = { status: 500 } as AxiosResponse;
      reportAxiosError(error, {
        url: "https://api.example/api/private?token=secret-token#fragment-secret",
        method: "get",
      });

      const body = String(vi.mocked(fetch).mock.calls[0][1]?.body);
      expect(JSON.parse(body)).toMatchObject({
        kind: "http-500",
        status: 500,
        url: "/api/private",
        browser_url: "/reset-password",
      });
      expect(body).not.toContain("secret-token");
      expect(body).not.toContain("fragment-secret");
      expect(body).not.toContain("api.example");
    } finally {
      window.history.replaceState({}, "", originalUrl);
    }
  });

  it("sends only browser paths for error and unhandledrejection reports", () => {
    const originalUrl = window.location.href;
    window.history.replaceState({}, "", "/reset-password?token=secret-token#fragment-secret");
    try {
      installGlobalErrorReporting();
      window.dispatchEvent(new ErrorEvent("error", { message: "global test error", filename: "/src/main.ts" }));
      const rejection = new Event("unhandledrejection");
      Object.defineProperty(rejection, "reason", { value: new Error("global test rejection") });
      window.dispatchEvent(rejection);

      const bodies = vi.mocked(fetch).mock.calls.map(([, init]) => String(init?.body));
      expect(bodies).toHaveLength(2);
      expect(JSON.parse(bodies[0])).toMatchObject({ kind: "uncaught-error", url: "/reset-password" });
      expect(JSON.parse(bodies[1])).toMatchObject({ kind: "unhandled-rejection", url: "/reset-password" });
      for (const body of bodies) {
        expect(body).not.toContain("secret-token");
        expect(body).not.toContain("fragment-secret");
      }
    } finally {
      window.history.replaceState({}, "", originalUrl);
    }
  });
});
