function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/**
 * Progressively interprets raw digits typed into a 24h HH:MM field, picking
 * whichever hour/minute split is valid. With 3 digits there are two possible
 * splits (1+2 or 2+1); whichever produces a valid HH (00-23) and MM (00-59)
 * wins. Never pads a still-partial minute digit here — that would consume
 * the "slot" a subsequent keystroke needs to land in (e.g. typing "123" then
 * "5" must extend to "12:35", not get stuck after an eagerly-padded "12:30").
 * Padding only happens once the field is finalized, via normalizeTime.
 */
export function formatTimeDigits(rawDigits: string): { display: string; valid: boolean } {
  const raw = rawDigits.slice(0, 4);
  if (raw.length === 0) return { display: "", valid: true };
  if (raw.length === 1) return { display: raw, valid: true };

  if (raw.length === 2) {
    const h = parseInt(raw, 10);
    if (h <= 23) return { display: raw, valid: true };
    return { display: `${raw[0]}:${raw[1]}`, valid: true };
  }

  if (raw.length === 3) {
    const m2 = parseInt(raw.slice(1), 10);
    if (m2 <= 59) return { display: `${raw[0]}:${raw.slice(1)}`, valid: true };
    const h2 = parseInt(raw.slice(0, 2), 10);
    if (h2 <= 23) return { display: `${raw.slice(0, 2)}:${raw[2]}`, valid: true };
    return { display: `${raw.slice(0, 2)}:${raw[2]}`, valid: false };
  }

  const hh = raw.slice(0, 2);
  const mm = raw.slice(2, 4);
  return { display: `${hh}:${mm}`, valid: parseInt(hh, 10) <= 23 && parseInt(mm, 10) <= 59 };
}

/**
 * Entry point for a raw keystroke buffer. The colon is always re-derived
 * from the digit count (formatTimeDigits inserts it in the right place on
 * its own) rather than parsed positionally — reading the colon back out of
 * our own previously-rendered display would truncate digits typed after it
 * once the display already shows two minute digits (e.g. continuing to
 * type "1235" after the field already reads "1:23" must still resolve to
 * "12:35", not get capped at "1:23"). Any ":" the user presses is simply
 * dropped; the colon reappears automatically as soon as enough digits are
 * typed, so the visible effect is the same as "typing a colon" without the
 * ambiguity of parsing it back out of formatted text.
 */
export function formatTimeInput(raw: string): { display: string; valid: boolean } {
  return formatTimeDigits(raw.replace(/\D/g, ""));
}

/**
 * Zero-pads a possibly-shorthand time into strict "HH:MM", for use once a
 * field is finalized (blur). A lone hour digit is treated as the complete
 * value ("8" -> "08"); a lone minute digit is treated as its tens digit
 * ("5" -> "50"), matching how it reads while typing left-to-right.
 */
export function normalizeTime(display: string): string {
  const [h = "", m = ""] = display.split(":");
  if (h === "" && m === "") return "";
  const hh = pad2(parseInt(h || "0", 10));
  const mm = m.length >= 2 ? pad2(parseInt(m, 10)) : pad2(parseInt(m || "0", 10) * 10);
  return `${hh}:${mm}`;
}
