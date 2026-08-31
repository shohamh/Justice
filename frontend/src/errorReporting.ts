import type { AxiosError, AxiosRequestConfig } from "axios";

const REPORT_URL = `${import.meta.env.VITE_API_BASE ?? "/api"}/client-errors`;
const REQUEST_ID_HEADER = "X-Request-ID";
const SENSITIVE = /password|token|secret|authorization|cookie|refresh|access/i;

// Caps how many times the *same* error can be reported in a burst — e.g. a
// render loop or a broken retry loop erroring on every tick — so it doesn't
// hammer the network/backend at all. Distinct errors are never affected: the
// limit is keyed per fingerprint. Configurable since the right threshold
// depends on the deployment; mirrors the backend's own per-fingerprint log
// rate limit (see error_logging.py) so the two defenses use the same policy.
const RATE_LIMIT_MAX_PER_WINDOW = Number(import.meta.env.VITE_ERROR_RATE_LIMIT_MAX_PER_WINDOW ?? 10);
const RATE_LIMIT_WINDOW_MS = Number(import.meta.env.VITE_ERROR_RATE_LIMIT_WINDOW_MS ?? 60_000);
const rateLimitState = new Map<string, { windowStart: number; count: number }>();
let errorReportingToken: string | null = null;

export function setErrorReportingToken(token: string | null): void {
  errorReportingToken = token;
}

function errorFingerprint(report: Record<string, unknown>): string {
  return [report.kind, report.message, report.filename, report.line, report.status].map(String).join("|");
}

function allowedByRateLimit(fingerprint: string): boolean {
  const now = Date.now();
  const entry = rateLimitState.get(fingerprint);
  if (!entry || now - entry.windowStart >= RATE_LIMIT_WINDOW_MS) {
    rateLimitState.set(fingerprint, { windowStart: now, count: 1 });
    return true;
  }
  if (entry.count < RATE_LIMIT_MAX_PER_WINDOW) {
    entry.count += 1;
    return true;
  }
  return false;
}

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
  if (!allowedByRateLimit(errorFingerprint(report))) return;
  void fetch(REPORT_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      [REQUEST_ID_HEADER]: String(report.request_id ?? "unknown"),
      ...(errorReportingToken ? { Authorization: `Bearer ${errorReportingToken}` } : {}),
    },
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
