import { describe, expect, it } from "vitest";
import { translateApiError } from "./translateApiError";

const dict: Record<string, string> = {
  "errors.generic": "שגיאה",
  "errors.overlap": "קיימת חפיפה עם תורנות אחרת",
  "errors.soldier_not_found": "חייל לא נמצא",
};

function t(key: string): string {
  return dict[key] ?? key;
}

function axiosErrorWithDetail(detail: unknown) {
  return { response: { data: { detail } } };
}

describe("translateApiError", () => {
  it("translates a known snake_case error code", () => {
    expect(translateApiError(axiosErrorWithDetail("overlap"), t)).toBe("קיימת חפיפה עם תורנות אחרת");
  });

  it("translates the prefix of a compound code:payload detail", () => {
    expect(translateApiError(axiosErrorWithDetail("soldier_not_found:9d2f"), t)).toBe("חייל לא נמצא");
  });

  it("falls back to the given fallback for an unmapped code", () => {
    expect(translateApiError(axiosErrorWithDetail("some_never_seen_code"), t, "ברירת מחדל")).toBe("ברירת מחדל");
  });

  it("falls back to the generic error when no fallback is given and detail is missing", () => {
    expect(translateApiError({}, t)).toBe("שגיאה");
  });

  it("falls back to the generic error for non-axios errors", () => {
    expect(translateApiError(new Error("boom"), t)).toBe("שגיאה");
  });
});
