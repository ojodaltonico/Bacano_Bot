from __future__ import annotations

from typing import Any


def normalize_argentine_phone(phone: Any) -> str | None:
    raw_phone = str(phone or "").strip()
    if not raw_phone:
        return None

    digits = extract_digits(raw_phone)
    if not digits:
        return None

    if digits.startswith("00"):
        digits = digits[2:]

    if digits.startswith("0"):
        digits = digits[1:]

    if digits.startswith("15") and len(digits) <= 10:
        return None

    if digits.startswith("549"):
        normalized = _normalize_international_mobile(digits)
    elif digits.startswith("54"):
        rest = digits[2:]
        if rest.startswith("9"):
            normalized = _normalize_international_mobile(f"54{rest}")
        else:
            local_number = _strip_local_mobile_prefix(rest)
            normalized = f"549{local_number}" if len(local_number) == 10 else None
    elif len(digits) == 10:
        normalized = f"549{digits}"
    elif len(digits) in {11, 12} and digits.startswith("9"):
        local_number = _strip_local_mobile_prefix(digits[1:])
        normalized = f"549{local_number}" if len(local_number) == 10 else None
    else:
        local_number = _strip_local_mobile_prefix(digits)
        normalized = f"549{local_number}" if len(local_number) == 10 else None

    if not normalized or not normalized.isdigit():
        return None
    if len(normalized) < 12 or len(normalized) > 14:
        return None
    if not normalized.startswith("549"):
        return None

    return normalized


def detect_phone_format(phone: Any) -> str:
    raw_phone = str(phone or "").strip()
    if not raw_phone:
        return "vacio"

    digits = extract_digits(raw_phone)
    if not digits:
        return "desconocido"

    if digits.startswith("549"):
        return "549_internacional"
    if digits.startswith("54") and len(digits) >= 12 and not digits.startswith("549"):
        return "54_sin_9"
    if digits.startswith("0"):
        return "local_con_0"
    if "15" in digits:
        return "contiene_15"
    if len(digits) == 10:
        return "local_10_digitos"
    return "desconocido"


def extract_digits(value: Any) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def count_phone_digits(phone: Any) -> int:
    return len(extract_digits(phone))


def mask_phone(phone: Any) -> str:
    digits = extract_digits(phone)
    if not digits:
        return ""
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


def _normalize_international_mobile(digits: str) -> str | None:
    if not digits.startswith("54"):
        return None

    rest = digits[2:]
    if rest.startswith("9"):
        local_number = _strip_local_mobile_prefix(rest[1:])
        return f"549{local_number}" if len(local_number) == 10 else None

    local_number = _strip_local_mobile_prefix(rest)
    return f"549{local_number}" if len(local_number) == 10 else None


def _strip_local_mobile_prefix(digits: str) -> str:
    if len(digits) in {11, 12}:
        idx = digits.find("15", 2)
        if idx != -1:
            area_length = idx
            subscriber_length = len(digits) - idx - 2
            if area_length in {2, 3, 4} and subscriber_length in {6, 7, 8}:
                return digits[:idx] + digits[idx + 2 :]
    return digits
