type TFn = (key: string, options?: Record<string, unknown>) => string;

/**
 * Backend errors are surfaced as a `detail` string that is either a stable
 * snake_case code (translated via the `errors.*` i18n namespace) or, for a
 * couple of legacy endpoints, a `prefix:payload` compound where only the
 * prefix is a translatable code (e.g. gimelim's `soldier_not_found:<id>`).
 * Never show `detail` to the user directly — always route it through here so
 * unmapped codes fall back to a Hebrew message instead of leaking English.
 *
 * Takes the caller's own `t` (from `useTranslation()`) rather than importing
 * the app's i18n singleton directly, so this module has no side effect on
 * import — components/tests that mock `react-i18next` without also stubbing
 * `initReactI18next` are unaffected. Detects a missing key by comparing the
 * result to the key itself (i18next's default missing-key behavior) rather
 * than relying on the `{ defaultValue }` option, since some test mocks of
 * `t` don't implement that option.
 */
function extractDetail(err: unknown): string | undefined {
  if (err && typeof err === "object" && "response" in err) {
    const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const fields = (detail as { loc?: string[] }[])
        .map((d) => d.loc?.slice(1).join(".") ?? "?")
        .join(", ");
      return fields ? `validation_error:${fields}` : undefined;
    }
  }
  return undefined;
}

function extractStatus(err: unknown): number | undefined {
  if (err && typeof err === "object" && "response" in err) {
    const status = (err as { response?: { status?: unknown } }).response?.status;
    return typeof status === "number" ? status : undefined;
  }
  return undefined;
}

export function translateApiError(err: unknown, t: TFn, fallback?: string): string {
  const fallbackText = fallback ?? t("errors.generic");
  const detail = extractDetail(err);
  if (!detail) {
    const status = extractStatus(err);
    if (status !== undefined && status >= 500) {
      const serverError = t("errors.server_error");
      return serverError === "errors.server_error" ? fallbackText : serverError;
    }
    return fallbackText;
  }
  if (detail.startsWith("validation_error:")) {
    const fields = detail.slice("validation_error:".length);
    return `${t("errors.validation_error", { defaultValue: "נתונים לא תקינים" })}: ${fields}`;
  }

  const code = detail.includes(":") ? detail.split(":")[0] : detail;
  const key = `errors.${code}`;
  const translated = t(key);
  return translated === key ? fallbackText : translated;
}
