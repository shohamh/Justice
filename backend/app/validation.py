import re

# Israeli mobile (05X) and landline (0[2,3,4,8,9]) numbers, with or without
# dashes/spaces as separators, and with an optional +972/972 country code
# prefix in place of the leading 0. Mirrors frontend/src/utils/phoneValidation.ts.
_ISRAELI_PHONE_RE = re.compile(r"^(?:\+?972|0)(5\d{8}|[23489]\d{7})$")


def is_valid_israeli_phone(phone: str) -> bool:
    digits = re.sub(r"[\s-]", "", phone)
    return bool(_ISRAELI_PHONE_RE.match(digits))
