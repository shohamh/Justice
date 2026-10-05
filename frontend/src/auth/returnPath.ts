type ReturnLocation = {
  pathname?: unknown;
  search?: unknown;
  hash?: unknown;
};

/** Return a validated same-origin path from React Router state, or null. */
export function safeInternalReturnPath(candidate: unknown): string | null {
  let target: string;

  if (typeof candidate === "string") {
    target = candidate;
  } else if (typeof candidate === "object" && candidate !== null && !Array.isArray(candidate)) {
    const location = candidate as ReturnLocation;
    if (
      typeof location.pathname !== "string" ||
      (location.search !== undefined && typeof location.search !== "string") ||
      (location.hash !== undefined && typeof location.hash !== "string")
    ) {
      return null;
    }
    target = `${location.pathname}${location.search ?? ""}${location.hash ?? ""}`;
  } else {
    return null;
  }

  if (
    !target.startsWith("/") ||
    target.startsWith("//") ||
    /[\\\u0000-\u001f\u007f-\u009f]/.test(target)
  ) {
    return null;
  }

  try {
    const parsed = new URL(target, window.location.origin);
    if (parsed.origin !== window.location.origin) return null;
  } catch {
    return null;
  }

  return target;
}
