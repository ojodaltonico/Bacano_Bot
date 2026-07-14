from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from integrations.woocommerce_client import WooCommerceClient


DEBUG_DIR = Path(__file__).resolve().parent / "debug"
OUTPUT_FILE = DEBUG_DIR / "woocommerce_non_cash_orders_sample.json"
PER_PAGE = 50
MAX_PAGES = 10
MAX_RESULTS = 5

EXACT_SENSITIVE_KEYS = {
    "first_name",
    "last_name",
    "full_name",
    "address_1",
    "address_2",
    "email",
    "phone",
    "customer_ip_address",
    "customer_user_agent",
    "ip",
    "user_agent",
    "order_key",
    "payment_url",
    "customer_note",
}

PARTIAL_SENSITIVE_KEYWORDS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "consumer_key",
    "consumer_secret",
    "access_key",
    "private",
    "note",
)

ADDRESS_FIELDS = {"city", "state", "postcode"}
META_ALLOWLIST = {
    "role",
    "user_role",
    "customer_role",
    "_customer_user_role",
}


def mask_value(label: str) -> str:
    return f"[REDACTED:{label}]"


def looks_like_ip(value: str) -> bool:
    return bool(re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", value))


def looks_like_email(value: str) -> bool:
    return bool(re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def looks_like_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return len(digits) >= 7


def is_url_with_key_param(value: str) -> bool:
    if "://" not in value:
        return False
    parsed = urlparse(value)
    return "key" in parse_qs(parsed.query)


def should_mask_key(key: str) -> bool:
    normalized = key.lower()
    if normalized in EXACT_SENSITIVE_KEYS or normalized in ADDRESS_FIELDS:
        return True
    return any(keyword in normalized for keyword in PARTIAL_SENSITIVE_KEYWORDS)


def sanitize_string(value: str, key: str) -> str:
    normalized = key.lower()
    if not value:
        return value
    if normalized in {"payment_url", "order_key"}:
        return mask_value(normalized)
    if should_mask_key(normalized):
        return mask_value(normalized)
    if looks_like_email(value):
        return mask_value(normalized or "email")
    if looks_like_ip(value):
        return mask_value(normalized or "ip")
    if is_url_with_key_param(value):
        return mask_value(normalized or "url_with_key")
    if normalized in {"first_name", "last_name", "full_name", "phone"}:
        return mask_value(normalized)
    if normalized in ADDRESS_FIELDS:
        return mask_value(normalized)
    if "mozilla/" in value.lower():
        return mask_value(normalized or "user_agent")
    if normalized == "transaction_id":
        return value
    return value


def sanitize_scalar(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return sanitize_string(value, key)
    if isinstance(value, (int, float, bool)):
        return value
    return mask_value(key.lower() or "value")


def sanitize_meta_data(meta_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized_items = []
    for item in meta_data:
        clean_item = {}
        for field, value in item.items():
            if field == "key":
                clean_item[field] = value
                continue
            if field == "id":
                clean_item[field] = value
                continue

            meta_key = str(item.get("key", "")).strip().lower()
            if field in {"display_key", "display_value"}:
                clean_item[field] = sanitize_scalar(value, f"{meta_key}_{field}")
                continue

            if meta_key in META_ALLOWLIST:
                clean_item[field] = value
                continue

            if isinstance(value, dict):
                clean_item[field] = sanitize_payload(value)
            elif isinstance(value, list):
                clean_item[field] = sanitize_payload(value)
            elif should_mask_key(meta_key):
                clean_item[field] = sanitize_scalar(value, meta_key or field)
            elif isinstance(value, str) and (
                looks_like_email(value)
                or looks_like_ip(value)
                or is_url_with_key_param(value)
                or "mozilla/" in value.lower()
            ):
                clean_item[field] = sanitize_scalar(value, meta_key or field)
            else:
                clean_item[field] = value
        sanitized_items.append(clean_item)
    return sanitized_items


def sanitize_line_items(line_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized_items = []
    for item in line_items:
        clean_item = {}
        for key, value in item.items():
            if key == "meta_data" and isinstance(value, list):
                clean_item[key] = sanitize_meta_data(value)
            elif key in {
                "id",
                "name",
                "product_id",
                "variation_id",
                "quantity",
                "subtotal",
                "total",
                "sku",
            }:
                clean_item[key] = value
            else:
                clean_item[key] = sanitize_payload(value, parent_key=key)
        sanitized_items.append(clean_item)
    return sanitized_items


def sanitize_payload(payload: Any, parent_key: str = "") -> Any:
    if isinstance(payload, list):
        return [sanitize_payload(item, parent_key=parent_key) for item in payload]

    if isinstance(payload, dict):
        sanitized = {}
        for key, value in payload.items():
            normalized = str(key).lower()

            if normalized == "meta_data" and isinstance(value, list):
                sanitized[key] = sanitize_meta_data(value)
                continue

            if normalized == "line_items" and isinstance(value, list):
                sanitized[key] = sanitize_line_items(value)
                continue

            if isinstance(value, dict):
                sanitized[key] = sanitize_payload(value, parent_key=normalized)
                continue

            if isinstance(value, list):
                sanitized[key] = sanitize_payload(value, parent_key=normalized)
                continue

            sanitized[key] = sanitize_scalar(value, normalized)
        return sanitized

    return payload


def get_tickera_meta_keys(order: dict[str, Any]) -> list[str]:
    keys = set()

    for item in order.get("meta_data") or []:
        key = str(item.get("key", "")).strip()
        if key.lower().startswith("tc_") or "_tc_" in key.lower():
            keys.add(key)

    for line_item in order.get("line_items") or []:
        for item in line_item.get("meta_data") or []:
            key = str(item.get("key", "")).strip()
            if key.lower().startswith("tc_") or "_tc_" in key.lower():
                keys.add(key)

    return sorted(keys)


def summarize_order(order: dict[str, Any]) -> str:
    order_id = order.get("id", "N/A")
    status = order.get("status", "N/A")
    created_at = order.get("date_created", "N/A")
    date_paid_present = "si" if bool(order.get("date_paid")) else "no"
    payment_method = order.get("payment_method") or "N/A"
    payment_method_title = order.get("payment_method_title") or "N/A"
    transaction_present = "si" if bool(order.get("transaction_id")) else "no"
    billing = order.get("billing") or {}
    phone_present = "si" if bool(billing.get("phone")) else "no"
    customer_id = order.get("customer_id", "N/A")
    line_items = order.get("line_items") or []
    products = []
    for item in line_items:
        name = item.get("name", "N/A")
        product_id = item.get("product_id", "N/A")
        variation_id = item.get("variation_id", "N/A")
        products.append(f"{name} (product_id={product_id}, variation_id={variation_id})")

    tickera_keys = get_tickera_meta_keys(order)
    tickera_summary = ", ".join(tickera_keys) if tickera_keys else "ninguna"
    products_summary = "; ".join(products) if products else "sin productos"

    return (
        f"Pedido {order_id} | estado={status} | fecha={created_at} | "
        f"fecha_pago={date_paid_present} | payment_method={payment_method} | "
        f"payment_method_title={payment_method_title} | transaction_id={transaction_present} | "
        f"telefono presente={phone_present} | customer_id={customer_id} | "
        f"productos={len(line_items)} | items={products_summary} | "
        f"tickera_meta_keys={tickera_summary}"
    )


def build_sample_payload(orders: list[dict[str, Any]], payment_counter: Counter[str]) -> dict[str, Any]:
    return {
        "order_count": len(orders),
        "payment_method_summary": dict(payment_counter),
        "orders": [sanitize_payload(order) for order in orders],
    }


def find_non_cash_orders(client: WooCommerceClient) -> list[dict[str, Any]]:
    found_orders: list[dict[str, Any]] = []

    for page in range(1, MAX_PAGES + 1):
        orders = client.get_orders(per_page=PER_PAGE, page=page)
        if not isinstance(orders, list):
            raise RuntimeError("La respuesta de WooCommerce no fue una lista de pedidos.")

        for order in orders:
            if (order.get("payment_method") or "").strip().lower() == "cod":
                continue
            found_orders.append(order)
            if len(found_orders) >= MAX_RESULTS:
                return found_orders

        if len(orders) < PER_PAGE:
            break

    return found_orders


def main() -> None:
    client = WooCommerceClient()
    orders = find_non_cash_orders(client)
    payment_counter = Counter((order.get("payment_method") or "unknown") for order in orders)

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    for order in orders:
        print(summarize_order(order))

    if not orders:
        print("No se encontraron pedidos con payment_method distinto de 'cod'.")

    print("Resumen por metodo de pago:")
    for payment_method, count in sorted(payment_counter.items()):
        print(f"{payment_method}: {count} pedidos")

    sample_payload = build_sample_payload(orders, payment_counter)
    OUTPUT_FILE.write_text(
        json.dumps(sample_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Muestra anonimizada guardada en: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
