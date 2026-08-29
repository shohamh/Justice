import type { AxiosError, AxiosRequestConfig } from "axios";

const REPORT_URL = `${import.meta.env.VITE_API_BASE ?? "/api"}/client-errors`;
const REQUEST_ID_HEADER = "X-Request-ID";
const SENSITIVE = /password|token|secret|authorization|cookie|refresh|access/i;

function redact(value: unknown, depth = 0): unknown {
  if (depth > 4) return "[truncated]";
  if (Array.isArray(value)) return value.slice(0, 50).map((item) => redact(item, depth + 1));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).slice(0, 100).map(([key, item]) => [
      key, SENSITIVE.test(key) ? "[redacted]" : redact(item, depth + 1),
    ]));
  }
  if (typeof value === "string" && value.length > 4000) return `${value.slice(0, 4000)}...[truncated]`;
  return value;
}

export function newRequestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function reportFrontendError(report: Record<string, unknown>): void {
  if (typeof window === "undefined" || report.url === REPORT_URL) return;
  void fetch(REPORT_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", [REQUEST_ID_HEADER]: String(report.request_id ?? "unknown") },
    body: JSON.stringify(redact(report)),
    keepalive: true,
  }).catch(() => undefined);
}

export function reportAxiosError(error: AxiosError, config?: AxiosRequestConfig): void {
  const request = config ?? error.config;
  const headers = request?.headers as Record<string, unknown> | undefined;
  reportFrontendError({
    kind: "http-500",
    request_id: headers?.[REQUEST_ID_HEADER] ?? headers?.[REQUEST_ID_HEADER.toLowerCase()] ?? error.response?.headers?.[REQUEST_ID_HEADER.toLowerCase()],
    message: error.message,
    stack: error.stack,
    url: request?.url,
    method: request?.method,
    status: error.response?.status,
    request_data: request?.data,
    response_data: error.response?.data,
    browser_url: window.location.href,
    user_agent: navigator.userAgent,
    response_headers: error.response?.headers,
  });
}

export function installGlobalErrorReporting(): void {
  if (typeof window === "undefined") return;
  window.addEventListener("error", (event) => {
    reportFrontendError({ kind: "uncaught-error", message: event.message, stack: event.error?.stack, url: window.location.href, filename: event.filename, line: event.lineno, column: event.colno, user_agent: navigator.userAgent });
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason as { message?: string; stack?: string } | undefined;
    reportFrontendError({ kind: "unhandled-rejection", message: reason?.message ?? String(event.reason), stack: reason?.stack, url: window.location.href, user_agent: navigator.userAgent });
  });
}
