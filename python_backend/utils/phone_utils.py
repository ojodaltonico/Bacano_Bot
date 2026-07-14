from __future__ import annotations

from typing import Any


def normalize_argentine_phone(phone: Any) -> str | None:
    raw_phone = str(phone or "").strip()
    if not raw_phone:
        return None

    digits = extract_digits(raw_phone)
    if not digits:
        return None

    if digits.startswith("0"):
        digits = digits[1:]

    if digits.startswith("549"):
        normalized = digits
    elif digits.startswith("54"):
        rest = digits[2:]
        if rest.startswith("9"):
            normalized = digits
        else:
            normalized = f"549{rest}"
    elif len(digits) == 10:
        normalized = f"549{digits}"
    elif len(digits) in {11, 12} and digits.startswith("9"):
        normalized = f"54{digits}"
    else:
        normalized = digits

    if normalized.startswith("549") and len(normalized) >= 13:
        idx = normalized.find("15", 3)
        if idx != -1:
            normalized = normalized[:idx] + normalized[idx + 2 :]

    if not normalized.isdigit():
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

