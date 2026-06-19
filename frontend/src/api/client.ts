import axios, { AxiosError } from "axios";

const baseURL = import.meta.env.VITE_API_BASE ?? "/api";

export const api = axios.create({
  baseURL,
  withCredentials: true,
});

let accessToken: string | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

let refreshing: Promise<string> | null = null;

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const originalRequest = error.config as (typeof error.config & { _retry?: boolean }) | undefined;
    // Never attempt a token refresh for the auth endpoints themselves: a 401 from
    // /auth/login means bad credentials, and /auth/refresh failing means re-login.
    const isAuthEndpoint = originalRequest?.url?.includes("/auth/");
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry && !isAuthEndpoint) {
      originalRequest._retry = true;
      try {
        if (!refreshing) {
          refreshing = api.post<{ access_token: string }>("/auth/refresh").then((r) => {
            setAccessToken(r.data.access_token);
            return r.data.access_token;
          }).finally(() => {
            refreshing = null;
          });
        }
        await refreshing;
        return api.request(originalRequest);
      } catch {
        setAccessToken(null);
        window.dispatchEvent(new Event("auth:session-expired"));
        throw error;
      }
    }
    throw error;
  },
);
