import {
  AxiosError,
  AxiosHeaders,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../errorReporting", () => ({
  newRequestId: vi.fn(() => "request-id-test"),
  reportAxiosError: vi.fn(),
  setErrorReportingToken: vi.fn(),
}));

import { reportAxiosError } from "../errorReporting";
import { api, getAccessToken, setAccessToken } from "./client";

function response(config: InternalAxiosRequestConfig, status: number, data: unknown): AxiosResponse {
  return {
    config,
    data,
    headers: new AxiosHeaders(),
    status,
    statusText: status === 200 ? "OK" : "Error",
  };
}

function fail(config: InternalAxiosRequestConfig, status: number): never {
  const result = response(config, status, { detail: "request failed" });
  throw new AxiosError(`Request failed with status code ${status}`, AxiosError.ERR_BAD_REQUEST, config, undefined, result);
}

describe("API client authentication and diagnostics", () => {
  let previousAdapter: typeof api.defaults.adapter;

  beforeEach(() => {
    previousAdapter = api.defaults.adapter;
    setAccessToken(null);
    vi.clearAllMocks();
  });

  afterEach(() => {
    api.defaults.adapter = previousAdapter;
  });

  it("adds the current Bearer token and a request ID", async () => {
    setAccessToken("access-token");
    let seen: InternalAxiosRequestConfig | undefined;
    api.defaults.adapter = (async (config) => {
      seen = config;
      return response(config, 200, { ok: true });
    }) as AxiosAdapter;

    await api.get("/protected");

    expect(seen?.headers.Authorization).toBe("Bearer access-token");
    expect(seen?.headers["X-Request-ID"]).toBe("request-id-test");
  });

  it("refreshes once with credentials and retries a protected 401 once", async () => {
    setAccessToken("expired-token");
    const seen: InternalAxiosRequestConfig[] = [];
    let protectedCalls = 0;
    api.defaults.adapter = (async (config) => {
      seen.push(config);
      if (config.url === "/auth/refresh") return response(config, 200, { access_token: "fresh-token" });
      protectedCalls += 1;
      if (protectedCalls === 1) fail(config, 401);
      return response(config, 200, { ok: true });
    }) as AxiosAdapter;

    await expect(api.get("/protected")).resolves.toMatchObject({ data: { ok: true } });

    const refreshCalls = seen.filter(({ url }) => url === "/auth/refresh");
    const protectedRequests = seen.filter(({ url }) => url === "/protected");
    expect(refreshCalls).toHaveLength(1);
    expect(refreshCalls[0].withCredentials).toBe(true);
    expect(protectedRequests).toHaveLength(2);
    expect(protectedRequests[1].headers.Authorization).toBe("Bearer fresh-token");
    expect(seen.every(({ headers }) => headers["X-Request-ID"] === "request-id-test")).toBe(true);
  });

  it("does not refresh a 401 from an auth endpoint", async () => {
    const urls: (string | undefined)[] = [];
    api.defaults.adapter = (async (config) => {
      urls.push(config.url);
      fail(config, 401);
    }) as AxiosAdapter;

    await expect(api.post("/auth/login", {})).rejects.toMatchObject({ response: { status: 401 } });

    expect(urls).toEqual(["/auth/login"]);
  });

  it("clears the access token and emits session-expired when refresh fails", async () => {
    setAccessToken("expired-token");
    const urls: (string | undefined)[] = [];
    const dispatchEvent = vi.fn();
    vi.stubGlobal("window", { dispatchEvent });
    api.defaults.adapter = (async (config) => {
      urls.push(config.url);
      fail(config, 401);
    }) as AxiosAdapter;

    try {
      await expect(api.get("/protected")).rejects.toMatchObject({ response: { status: 401 } });
      expect(urls).toEqual(["/protected", "/auth/refresh"]);
      expect(getAccessToken()).toBeNull();
      expect(dispatchEvent).toHaveBeenCalledOnce();
      expect(dispatchEvent.mock.calls[0][0]).toMatchObject({ type: "auth:session-expired" });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("reports an HTTP 500 response", async () => {
    api.defaults.adapter = (async (config) => fail(config, 500)) as AxiosAdapter;

    await expect(api.get("/broken")).rejects.toMatchObject({ response: { status: 500 } });

    expect(reportAxiosError).toHaveBeenCalledOnce();
  });
});
