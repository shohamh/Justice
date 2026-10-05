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

  const hasControlCharacter = [...target].some((character) => {
    const codePoint = character.codePointAt(0)!;
    return codePoint <= 0x1f || (codePoint >= 0x7f && codePoint <= 0x9f);
  });

  if (!target.startsWith("/") || target.startsWith("//") || target.includes("\\") || hasControlCharacter) {
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
