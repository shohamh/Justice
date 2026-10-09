import { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";

vi.mock("../errorReporting", () => ({
  newRequestId: () => "req-id",
  reportAxiosError: vi.fn(),
  setErrorReportingToken: vi.fn(),
}));

type Client = typeof import("./client");

interface Sent {
  url: string;
  authorization: string | undefined;
}

/**
 * Loads a fresh copy of the client (module state: access token and the in-flight
 * refresh) and replaces the network with a fake: /auth/refresh answers with a
 * token once `releaseRefresh` is called; every other URL answers 401 without a
 * bearer token and 200 with one.
 */
async function loadClient() {
  vi.resetModules();
  const client: Client = await import("./client");
  const sent: Sent[] = [];
  const refreshTimeouts: (number | undefined)[] = [];
  let releaseRefresh: (status: number) => void = () => {};
  const adapter: AxiosAdapter = (config: InternalAxiosRequestConfig) => {
    const url = config.url ?? "";
    const authorization = config.headers?.Authorization as string | undefined;
    sent.push({ url, authorization });
    const respond = (status: number, data: unknown) => {
      const response = { data, status, statusText: String(status), headers: {}, config };
      if (status >= 400) {
        return Promise.reject(Object.assign(new Error(`status ${status}`), {
          isAxiosError: true,
          config,
          response,
        }));
      }
      return Promise.resolve(response);
    };
    if (url === "/auth/refresh") {
      refreshTimeouts.push(config.timeout);
      return new Promise((resolve, reject) => {
        releaseRefresh = (status) => {
          respond(status, status === 200 ? { access_token: "fresh-token" } : {}).then(resolve, reject);
        };
        // Like axios' own xhr/http adapters: a request with `timeout` set rejects
        // with ECONNABORTED and no response once it elapses.
        if (config.timeout) {
          setTimeout(() => {
            reject(new AxiosError(`timeout of ${config.timeout}ms exceeded`, AxiosError.ECONNABORTED, config));
          }, config.timeout);
        }
      });
    }
    return authorization ? respond(200, { ok: true }) : respond(401, {});
  };
  client.api.defaults.adapter = adapter;
  return { client, sent, refreshTimeouts, release: (status: number) => releaseRefresh(status) };
}

const flush = async () => {
  for (let i = 0; i < 10; i++) await Promise.resolve();
};

describe("api client token refresh", () => {
  // Node test environment: the client signals an expired session on `window`.
  beforeEach(() => vi.stubGlobal("window", new EventTarget()));
  afterEach(() => vi.unstubAllGlobals());

  it("shares one /auth/refresh between session restore and a request sent while it is in flight", async () => {
    const { client, sent, release } = await loadClient();

    const restore = client.refreshAccessToken();
    const settings = client.api.get("/settings/public");
    await flush();
    release(200);

    await expect(restore).resolves.toBe("fresh-token");
    await expect(settings).resolves.toMatchObject({ status: 200 });
    expect(sent.filter((s) => s.url === "/auth/refresh")).toHaveLength(1);
    // The request waited for the refresh instead of going out unauthenticated.
    expect(sent.filter((s) => s.url === "/settings/public")).toEqual([
      { url: "/settings/public", authorization: "Bearer fresh-token" },
    ]);
  });

  it("joins the in-flight refresh when a 401 arrives during session restore", async () => {
    const { client, sent, release } = await loadClient();

    // An unauthenticated request goes out before anything starts a refresh.
    const settings = client.api.get("/settings/public");
    await flush();
    const restore = client.refreshAccessToken();
    await flush();
    release(200);

    await expect(restore).resolves.toBe("fresh-token");
    await expect(settings).resolves.toMatchObject({ status: 200 });
    expect(sent.filter((s) => s.url === "/auth/refresh")).toHaveLength(1);
  });

  it("still sends the waiting request when the refresh fails, and reports the session as expired", async () => {
    const { client, sent, release } = await loadClient();
    const expired = vi.fn();
    window.addEventListener("auth:session-expired", expired);

    const restore = client.refreshAccessToken();
    const settings = client.api.get("/settings/public");
    await flush();
    release(401);

    await expect(restore).rejects.toMatchObject({ response: { status: 401 } });
    // The request goes out without a token, its 401 starts a second refresh (the
    // first one is settled), which fails too: the session is reported expired.
    await flush();
    release(401);
    await expect(settings).rejects.toMatchObject({ response: { status: 401 } });
    expect(sent.filter((s) => s.url === "/settings/public")).toHaveLength(1);
    expect(expired).toHaveBeenCalledTimes(1);
    window.removeEventListener("auth:session-expired", expired);
  });

  it("discards a refresh that resolves after another user's token was installed", async () => {
    const { client, release } = await loadClient();
    const expired = vi.fn();
    window.addEventListener("auth:session-expired", expired);

    const refresh = client.refreshAccessToken();
    const settled = expect(refresh).rejects.toBeInstanceOf(client.StaleRefreshError);
    await flush();
    client.setAccessToken("user-b");
    release(200);

    await settled;
    expect(client.getAccessToken()).toBe("user-b");
    expect(expired).not.toHaveBeenCalled();
    window.removeEventListener("auth:session-expired", expired);
  });

  it("does not reinstall a token or expire the session when logout happens during a 401-triggered refresh", async () => {
    const { client, release } = await loadClient();
    const expired = vi.fn();
    window.addEventListener("auth:session-expired", expired);

    const settings = client.api.get("/settings/public");
    // Let the unauthenticated request 401 and start its refresh.
    await new Promise((resolve) => setTimeout(resolve, 0));
    client.setAccessToken(null);
    release(200);

    await expect(settings).rejects.toMatchObject({ response: { status: 401 } });
    expect(client.getAccessToken()).toBeNull();
    expect(expired).not.toHaveBeenCalled();
    window.removeEventListener("auth:session-expired", expired);
  });
  it("does not expire a newly signed-in session when a refresh from the previous session fails", async () => {
    const { client, release } = await loadClient();
    const expired = vi.fn();
    window.addEventListener("auth:session-expired", expired);

    const settings = client.api.get("/settings/public");
    // Let the unauthenticated request 401 and start its refresh.
    await new Promise((resolve) => setTimeout(resolve, 0));
    client.setAccessToken("user-b");
    release(401);

    await expect(settings).rejects.toMatchObject({ response: { status: 401 } });
    expect(client.getAccessToken()).toBe("user-b");
    expect(expired).not.toHaveBeenCalled();
    window.removeEventListener("auth:session-expired", expired);
  });
});

describe("api client refresh timeout", () => {
  beforeEach(() => {
    vi.stubGlobal("window", new EventTarget());
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("puts a timeout on /auth/refresh only, not on the shared instance", async () => {
    const { client, refreshTimeouts } = await loadClient();
    void client.refreshAccessToken().catch(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    expect(refreshTimeouts).toEqual([client.REFRESH_TIMEOUT_MS]);
    expect(client.REFRESH_TIMEOUT_MS).toBe(15_000);
    expect(client.api.defaults.timeout ?? 0).toBe(0);
    await vi.advanceTimersByTimeAsync(client.REFRESH_TIMEOUT_MS);
  });

  it("rejects a never-settling refresh after the timeout and clears the in-flight refresh", async () => {
    const { client, sent } = await loadClient();
    const refresh = client.refreshAccessToken();
    const settled = expect(refresh).rejects.toBeInstanceOf(client.RefreshTimeoutError);

    await vi.advanceTimersByTimeAsync(client.REFRESH_TIMEOUT_MS - 1);
    // Still the same single flight just before the deadline.
    expect(client.refreshAccessToken()).toBe(refresh);
    await vi.advanceTimersByTimeAsync(1);
    await settled;

    // `refreshing` was cleared: the next call starts a new request.
    const again = client.refreshAccessToken();
    expect(again).not.toBe(refresh);
    await vi.advanceTimersByTimeAsync(0);
    expect(sent.filter((s) => s.url === "/auth/refresh")).toHaveLength(2);
    void again.catch(() => undefined);
    await vi.advanceTimersByTimeAsync(client.REFRESH_TIMEOUT_MS);
  });

  it("releases a request waiting on a timed-out refresh without expiring the session", async () => {
    const { client, sent } = await loadClient();
    const expired = vi.fn();
    window.addEventListener("auth:session-expired", expired);

    const restore = client.refreshAccessToken();
    const restoreSettled = expect(restore).rejects.toBeInstanceOf(client.RefreshTimeoutError);
    const settings = client.api.get("/settings/public");
    const settingsSettled = expect(settings).rejects.toMatchObject({ response: { status: 401 } });
    await vi.advanceTimersByTimeAsync(0);
    expect(sent.filter((s) => s.url === "/settings/public")).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(client.REFRESH_TIMEOUT_MS);
    await restoreSettled;
    // Released: it went out (no token, so 401) and its 401 started a second refresh.
    expect(sent.filter((s) => s.url === "/settings/public")).toHaveLength(1);
    expect(sent.filter((s) => s.url === "/auth/refresh")).toHaveLength(2);

    // That refresh times out too: the request fails with its own 401, but a
    // timeout is not the server rejecting the session, so it is not expired.
    await vi.advanceTimersByTimeAsync(client.REFRESH_TIMEOUT_MS);
    await settingsSettled;
    expect(expired).not.toHaveBeenCalled();
    window.removeEventListener("auth:session-expired", expired);
  });

  it("keeps the current token when a 401-triggered refresh times out", async () => {
    const { client, release } = await loadClient();
    const expired = vi.fn();
    window.addEventListener("auth:session-expired", expired);
    client.setAccessToken("old-token");

    // Stale access token -> server 401s it. Simulate by forcing a 401 for this URL.
    client.api.defaults.adapter = ((orig) => (config: InternalAxiosRequestConfig) => {
      if (config.url === "/me") {
        return Promise.reject(Object.assign(new Error("status 401"), {
          isAxiosError: true,
          config,
          response: { data: {}, status: 401, statusText: "401", headers: {}, config },
        }));
      }
      return (orig as AxiosAdapter)(config);
    })(client.api.defaults.adapter);

    const me = client.api.get("/me");
    const meSettled = expect(me).rejects.toMatchObject({ response: { status: 401 } });
    await vi.advanceTimersByTimeAsync(client.REFRESH_TIMEOUT_MS);
    await meSettled;
    expect(expired).not.toHaveBeenCalled();
    expect(client.getAccessToken()).toBe("old-token");
    release(200); // late answer to the timed-out request is ignored by axios
    window.removeEventListener("auth:session-expired", expired);
  });
});
