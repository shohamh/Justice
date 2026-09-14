import type { TFunction } from "i18next";
import type { RangeCandidate } from "../api/ranges";

const SYSTEM_REASON_TEMPLATES: Record<string, [string, string]> = {
  recent: ["ranges.system_reason_recent", "מטווחים בוצעו לאחרונה, יפוג תוקף ב־{{date}}"],
  valid_expiring: ["ranges.system_reason_valid", "מטווחים בתוקף, עומדים לפוג ב־{{date}}"],
  last_completed: ["ranges.system_reason_last", "מטווח אחרון ב־{{date}}"],
  never_completed: ["ranges.system_reason_never", "מעולם לא ביצע מטווחים"],
};

/**
 * Human-readable explanation for why a range candidate was ranked where they
 * were. Prefers the machine-readable system_reason_code + system_reason_date
 * (translated via i18n, so the UI never shows a raw code like
 * "range_never_completed") over the free-text explanation field, which is
 * only a fallback for reasons that don't have a system_reason_code (e.g.
 * duty_priority).
 */
export function formatRangeCandidateReason(candidate: RangeCandidate, t: TFunction): string {
  const date = candidate.system_reason_date
    ? candidate.system_reason_date.split("-").reverse().join(".")
    : "";
  const template = SYSTEM_REASON_TEMPLATES[candidate.system_reason_code ?? ""];
  if (template) {
    const translated = t(template[0], { date });
    return translated === template[0] ? template[1].replace("{{date}}", date) : translated;
  }
  const key = `ranges.assignment_reasons.${candidate.reason_code}`;
  const translated = t(key);
  return translated === key ? candidate.explanation || candidate.reason_code : translated;
}
