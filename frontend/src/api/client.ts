import axios, { AxiosError } from "axios";
import { newRequestId, reportAxiosError, setErrorReportingToken } from "../errorReporting";

const baseURL = import.meta.env.VITE_API_BASE ?? "/api";

export const api = axios.create({
  baseURL,
  withCredentials: true,
});

let accessToken: string | null = null;
// Bumped on every token change; a refresh that started under an older epoch belongs
// to a previous session (logout/login happened meanwhile) and must be discarded.
let tokenEpoch = 0;

/** A refresh answered after the access token was replaced (logout / another login). */
export class StaleRefreshError extends Error {}

export function setAccessToken(token: string | null) {
  accessToken = token;
  tokenEpoch += 1;
  setErrorReportingToken(token);
}

export function getAccessToken(): string | null {
  return accessToken;
}

/**
 * The refresh alone gets a deadline (the shared instance deliberately has none:
 * exports and uploads may legitimately run long). While the access token is null,
 * every non-auth request waits on the in-flight refresh, so a hung refresh would
 * otherwise freeze the whole app.
 */
export const REFRESH_TIMEOUT_MS = 15_000;

/**
 * The refresh got no answer within REFRESH_TIMEOUT_MS. Not an auth failure: the
 * server never said the session is invalid, so the 401 handler does not expire it.
 */
export class RefreshTimeoutError extends Error {}

const isTimeout = (e: unknown) =>
  axios.isAxiosError(e) && !e.response && (e.code === AxiosError.ECONNABORTED || e.code === AxiosError.ETIMEDOUT);

let refreshing: Promise<string> | null = null;

/**
 * Exchanges the refresh cookie for a new access token. Single-flight: every
 * caller (session restore on startup, the 401 handler below) shares the one
 * request in flight instead of each starting its own.
 */
export function refreshAccessToken(): Promise<string> {
  if (!refreshing) {
    const startedAt = tokenEpoch;
    refreshing = api.post<{ access_token: string }>("/auth/refresh", undefined, { timeout: REFRESH_TIMEOUT_MS }).then((r) => {
      // Logout/login replaced the token while this was in flight: the answer belongs
      // to the previous cookie owner and must not become the current session's token.
      if (tokenEpoch !== startedAt) throw new StaleRefreshError();
      setAccessToken(r.data.access_token);
      return r.data.access_token;
    }).catch((e) => {
      // A failure answered after the token was replaced is not about the current session either.
      if (tokenEpoch !== startedAt) throw new StaleRefreshError();
      if (isTimeout(e)) throw new RefreshTimeoutError("refresh timed out", { cause: e });
      throw e;
    }).finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

// Never wait on or trigger a token refresh for the auth endpoints themselves: a
// 401 from /auth/login means bad credentials, and /auth/refresh failing means re-login.
const isAuthEndpoint = (url: string | undefined) => url?.includes("/auth/") ?? false;

api.interceptors.request.use(async (config) => {
  config.headers["X-Request-ID"] = newRequestId();
  // A request issued while the startup session restore is still refreshing would
  // otherwise go out without a token, get a 401 and be sent a second time.
  if (!accessToken && refreshing && !isAuthEndpoint(config.url)) {
    await refreshing.catch(() => undefined);
  }
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const originalRequest = error.config as (typeof error.config & { _retry?: boolean }) | undefined;
    if (error.response?.status === 500) {
      reportAxiosError(error, originalRequest);
    }
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry && !isAuthEndpoint(originalRequest.url)) {
      originalRequest._retry = true;
      try {
        await refreshAccessToken();
        return api.request(originalRequest);
      } catch (e) {
        // A stale refresh says nothing about the current session, and a timed-out
        // one got no answer at all: keep the session (the next 401 retries). Other
        // failures, including a plain network error, still expire it as before.
        if (e instanceof StaleRefreshError || e instanceof RefreshTimeoutError) throw error;
        setAccessToken(null);
        window.dispatchEvent(new Event("auth:session-expired"));
        throw error;
      }
    }
    throw error;
  },
);
