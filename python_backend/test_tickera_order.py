from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from integrations.tickera_client import TickeraClient


DEBUG_DIR = Path(__file__).resolve().parent / "debug"
PER_PAGE = 50
MAX_PAGES = 20

SENSITIVE_KEYWORDS = (
    "first_name",
    "last_name",
    "buyer_first",
    "buyer_last",
    "buyer_name",
    "email",
    "phone",
    "address",
    "ip",
    "user_agent",
    "password",
    "secret",
    "token",
    "api_key",
    "order_key",
    "payment_url",
    "name_post_meta",
)

VISIBLE_STRING_KEYS = {
    "transaction_id",
    "checksum",
    "ticket_type",
    "ticket_type_name",
    "ticket_type_title",
    "allowed_checkins",
    "checkins",
    "check_in_status",
    "checkin_status",
    "checkin_date",
    "date_checked_in",
    "date_checked",
    "ticket_status",
    "status",
    "barcode_type",
}

REDACTED_CUSTOM_FIELDS = {
    "buyer name",
    "buyer e-mail",
    "buyer email",
    "phone",
    "telephone",
    "first name",
    "last name",
}


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(keyword in normalized for keyword in SENSITIVE_KEYWORDS)


def is_private_url(value: str) -> bool:
    if "://" not in value:
        return False
    parsed = urlparse(value)
    private_params = {"key", "token", "secret", "api_key", "order_key", "signature"}
    return any(param.lower() in private_params for param in parse_qs(parsed.query))


def looks_like_email(value: str) -> bool:
    return bool(re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def looks_like_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return len(digits) >= 7


def looks_like_ip(value: str) -> bool:
    return bool(re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", value))


def sanitize_scalar(value: Any, key: str) -> Any:
    if value is None:
        return None

    if isinstance(value, (int, float, bool)):
        return value

    if not isinstance(value, str):
        return "[REDACTED]"

    normalized = key.lower()
    if not value:
        return value

    if normalized in VISIBLE_STRING_KEYS:
        return value
    if is_sensitive_key(normalized):
        return "[REDACTED]"
    if is_private_url(value):
        return "[REDACTED_URL]"
    if looks_like_email(value):
        return "[REDACTED]"
    if looks_like_phone(value):
        return "[REDACTED]"
    if looks_like_ip(value):
        return "[REDACTED]"
    if "mozilla/" in value.lower():
        return "[REDACTED]"

    return value


def sanitize_custom_field_entry(entry: Any) -> Any:
    if not isinstance(entry, list) or len(entry) < 2:
        return sanitize_payload(entry)

    label = str(entry[0])
    value = entry[1]
    sanitized = list(entry)
    if label.strip().lower() in REDACTED_CUSTOM_FIELDS:
        sanitized[1] = "[REDACTED]"
    else:
        sanitized[1] = sanitize_payload(value, label)

    for index in range(2, len(sanitized)):
        sanitized[index] = sanitize_payload(sanitized[index], label)

    return sanitized


def sanitize_payload(payload: Any, key: str = "") -> Any:
    if isinstance(payload, dict):
        sanitized = {}
        for item_key, item_value in payload.items():
            normalized = str(item_key).lower()
            if normalized == "custom_fields" and isinstance(item_value, list):
                sanitized[item_key] = [sanitize_custom_field_entry(item) for item in item_value]
            elif isinstance(item_value, (dict, list)):
                sanitized[item_key] = sanitize_payload(item_value, normalized)
            else:
                sanitized[item_key] = sanitize_scalar(item_value, normalized)
        return sanitized

    if isinstance(payload, list):
        return [sanitize_payload(item, key) for item in payload]

    return sanitize_scalar(payload, key)


def get_nested_dict(ticket: dict[str, Any], key: str) -> dict[str, Any]:
    value = ticket.get(key)
    return value if isinstance(value, dict) else {}


def get_transaction_id(ticket: dict[str, Any]) -> str:
    data = get_nested_dict(ticket, "data")
    transaction_id = data.get("transaction_id")
    return "" if transaction_id is None else str(transaction_id)


def matches_order(transaction_id: str, order_id: str, expected_prefix: str) -> bool:
    return transaction_id == order_id or transaction_id.startswith(expected_prefix)


def extract_correlative(transaction_id: str, order_id: str) -> int:
    if transaction_id == order_id:
        return 0

    if transaction_id.startswith(f"{order_id}-"):
        suffix = transaction_id.rsplit("-", 1)[-1]
        if suffix.isdigit():
            return int(suffix)

    return 999999


def get_custom_field_value(ticket: dict[str, Any], field_name: str) -> str:
    data = get_nested_dict(ticket, "data")
    custom_fields = data.get("custom_fields")
    if not isinstance(custom_fields, list):
        return "N/A"

    for entry in custom_fields:
        if (
            isinstance(entry, list)
            and len(entry) >= 2
            and str(entry[0]).strip().lower() == field_name.lower()
        ):
            return str(entry[1])
    return "N/A"


def get_ticket_type(ticket: dict[str, Any]) -> Any:
    data = get_nested_dict(ticket, "data")
    for candidate in (
        "ticket_type",
        "ticket_type_name",
        "ticket_type_title",
        "ticket_type_post_title",
        "ticket_name",
        "ticket_title",
    ):
        if data.get(candidate) not in (None, ""):
            return data.get(candidate)
        if ticket.get(candidate) not in (None, ""):
            return ticket.get(candidate)

    custom_ticket_type = get_custom_field_value(ticket, "Ticket Type")
    if custom_ticket_type != "N/A":
        return custom_ticket_type

    return "N/A"


def get_event_name(ticket: dict[str, Any]) -> str:
    data = get_nested_dict(ticket, "data")
    for candidate in ("event_name", "event_title", "event"):
        if data.get(candidate) not in (None, ""):
            return str(data.get(candidate))
        if ticket.get(candidate) not in (None, ""):
            return str(ticket.get(candidate))

    return get_custom_field_value(ticket, "Event")


def get_checkins_allowed(ticket: dict[str, Any]) -> Any:
    data = get_nested_dict(ticket, "data")
    for candidate in ("allowed_checkins", "checkins", "checkins_allowed"):
        if data.get(candidate) not in (None, ""):
            return data.get(candidate)
        if ticket.get(candidate) not in (None, ""):
            return ticket.get(candidate)
    return "N/A"


def was_used(ticket: dict[str, Any]) -> str:
    data = get_nested_dict(ticket, "data")
    date_checked = data.get("date_checked")
    if date_checked not in (None, ""):
        return "si"

    for candidate in ("checkin_date", "date_checked_in", "checked_in_at", "date_of_checkin"):
        if data.get(candidate):
            return "si"
        if ticket.get(candidate):
            return "si"
    return "no"


def get_checksum(ticket: dict[str, Any]) -> str:
    data = get_nested_dict(ticket, "data")
    checksum = data.get("checksum")
    return "" if checksum is None else str(checksum)


def get_ticket_identifier(ticket: dict[str, Any], fallback_index: int) -> str:
    return str(ticket.get("ticket_id", ticket.get("id", fallback_index)))


def summarize_ticket(ticket: dict[str, Any], found_page: int, order_id: str) -> str:
    transaction_id = get_transaction_id(ticket)
    checksum = get_checksum(ticket)
    correlative = extract_correlative(transaction_id, order_id)
    correlative_label = str(correlative) if correlative != 999999 else "N/A"
    checksum_present = "si" if bool(checksum) else "no"
    checksum_matches = "si" if checksum and checksum == transaction_id else "no"

    return (
        f"correlativo={correlative_label} | transaction_id={transaction_id or 'N/A'} | "
        f"checksum={checksum_present} | checksum_equals_transaction_id={checksum_matches} | "
        f"tipo_entrada={get_ticket_type(ticket)} | evento={get_event_name(ticket)} | "
        f"checkins_permitidos={get_checkins_allowed(ticket)} | ya_utilizado={was_used(ticket)} | "
        f"pagina_tickera={found_page}"
    )


def parse_order_id(argv: list[str]) -> str:
    if len(argv) != 2:
        raise SystemExit(
            "Uso: python python_backend/test_tickera_order.py <woocommerce_order_id>"
        )
    order_id = argv[1].strip()
    if not order_id:
        raise SystemExit("El ID del pedido WooCommerce es obligatorio.")
    return order_id


def find_tickets_for_order(
    client: TickeraClient, order_id: str
) -> tuple[list[dict[str, Any]], dict[int, int], dict[str, int], str]:
    matches: list[dict[str, Any]] = []
    pages_found: dict[int, int] = {}
    ticket_pages: dict[str, int] = {}
    expected_prefix = f"{order_id}-"
    found_any = False

    for page in range(1, MAX_PAGES + 1):
        tickets = client.get_tickets(per_page=PER_PAGE, page=page)
        if not tickets:
            break

        page_matches = 0
        for ticket in tickets:
            if not isinstance(ticket, dict):
                continue

            transaction_id = get_transaction_id(ticket)
            if matches_order(transaction_id, order_id, expected_prefix):
                matches.append(ticket)
                page_matches += 1
                ticket_pages[get_ticket_identifier(ticket, len(matches) - 1)] = page
                found_any = True

        if page_matches:
            pages_found[page] = page_matches

        if found_any:
            break

        if len(tickets) < PER_PAGE:
            break

    matches.sort(
        key=lambda ticket: (
            extract_correlative(get_transaction_id(ticket), order_id),
            get_transaction_id(ticket),
        )
    )

    return matches, pages_found, ticket_pages, expected_prefix


def build_output_payload(
    order_id: str,
    expected_prefix: str,
    tickets: list[dict[str, Any]],
    pages_found: dict[int, int],
    ticket_pages: dict[str, int],
) -> dict[str, Any]:
    checksums_match = all(
        get_checksum(ticket) == get_transaction_id(ticket)
        for ticket in tickets
        if get_checksum(ticket)
    )

    return {
        "woocommerce_order_id": order_id,
        "expected_prefix": expected_prefix,
        "ticket_count": len(tickets),
        "all_checksums_match_transaction_ids": checksums_match,
        "pages_found": pages_found,
        "ticket_pages": ticket_pages,
        "tickets": sanitize_payload(tickets),
    }


def main() -> None:
    order_id = parse_order_id(sys.argv)
    client = TickeraClient()
    tickets, pages_found, ticket_pages, expected_prefix = find_tickets_for_order(
        client, order_id
    )

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    output_file = DEBUG_DIR / f"tickera_order_{order_id}_sample.json"

    print(f"ID del pedido buscado: {order_id}")
    print(f"Cantidad de tickets encontrados: {len(tickets)}")

    for ticket in tickets:
        ticket_identifier = get_ticket_identifier(ticket, 0)
        found_page = ticket_pages.get(ticket_identifier, 0)
        print(summarize_ticket(ticket, found_page, order_id))

    output_file.write_text(
        json.dumps(
            build_output_payload(
                order_id,
                expected_prefix,
                tickets,
                pages_found,
                ticket_pages,
            ),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Muestra anonimizada guardada en: {output_file}")


if __name__ == "__main__":
    main()
