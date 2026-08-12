import { describe, expect, it } from "vitest";
import { translateApiError } from "./translateApiError";
import i18n from "../i18n";

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

  it("surfaces field names for a Pydantic-style list detail instead of the generic fallback", () => {
    const tWithDefault = (key: string, options?: Record<string, unknown>) =>
      dict[key] ?? (options?.defaultValue as string) ?? key;
    const err = axiosErrorWithDetail([
      { loc: ["body", "settings", "eligible_node_ids"], msg: "bad", type: "value_error" },
    ]);
    const msg = translateApiError(err, tWithDefault, "fallback");
    expect(msg).toContain("settings.eligible_node_ids");
    expect(msg).not.toBe("fallback");
  });

  // Regression test: medical_exemption_requires_file and start_date_required
  // were only added under register.errors.* (consumed by RegisterPage's own
  // error-mapping), not the flat top-level errors.* namespace that
  // translateApiError looks up. Pages that route errors through
  // translateApiError (e.g. MyRequestsPage) showed a generic fallback for
  // these two real server error codes instead of a real message. Uses the
  // app's actual i18n instance (real he.json), not the mock dict above, so
  // this only passes if the keys genuinely exist at errors.<code>.
  it("resolves medical_exemption_requires_file via the real he.json errors namespace", () => {
    const msg = translateApiError(axiosErrorWithDetail("medical_exemption_requires_file"), i18n.t.bind(i18n), "fallback");
    expect(msg).not.toBe("fallback");
    expect(msg).toBe("יש לצרף מסמך רפואי לבקשת פטור רפואי");
  });

  it("resolves start_date_required via the real he.json errors namespace", () => {
    const msg = translateApiError(axiosErrorWithDetail("start_date_required"), i18n.t.bind(i18n), "fallback");
    expect(msg).not.toBe("fallback");
    expect(msg).toBe("יש למלא תאריך התחלה כאשר מוזן תאריך סיום");
  });
});
