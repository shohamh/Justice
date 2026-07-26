// Israeli mobile (05X) and landline (0[2,3,4,8,9]) numbers, with or without
// dashes/spaces as separators, and with an optional +972/972 country code
// prefix in place of the leading 0.
const ISRAELI_PHONE_RE = /^(?:\+?972|0)(5\d{8}|[23489]\d{7})$/;

export function isValidIsraeliPhone(phone: string): boolean {
  const digits = phone.replace(/[\s-]/g, "");
  return ISRAELI_PHONE_RE.test(digits);
}
