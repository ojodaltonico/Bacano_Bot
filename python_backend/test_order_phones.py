from __future__ import annotations

import sys

from integrations.woocommerce_client import WooCommerceAPIError, WooCommerceClient
from utils.phone_utils import (
    count_phone_digits,
    detect_phone_format,
    mask_phone,
    normalize_argentine_phone,
)


def parse_args(argv: list[str]) -> tuple[str, int]:
    if len(argv) == 3 and argv[1] == "--limit" and argv[2].isdigit():
        limit = int(argv[2])
        if limit <= 0:
            raise SystemExit("El valor de --limit debe ser mayor que 0.")
        return "limit", limit

    if len(argv) == 3 and argv[1] == "--order-id" and argv[2].isdigit():
        order_id = int(argv[2])
        if order_id <= 0:
            raise SystemExit("El valor de --order-id debe ser mayor que 0.")
        return "order", order_id

    raise SystemExit(
        "Uso: python python_backend/test_order_phones.py --limit 50 | "
        "python python_backend/test_order_phones.py --order-id 39147"
    )


def build_phone_report(order: dict) -> dict[str, object]:
    billing = order.get("billing") if isinstance(order.get("billing"), dict) else {}
    raw_phone = billing.get("phone") if isinstance(billing, dict) else None
    normalized_phone = normalize_argentine_phone(raw_phone)

    return {
        "order_id": int(order.get("id") or 0),
        "payment_method": str(order.get("payment_method") or ""),
        "phone_present": bool(str(raw_phone or "").strip()),
        "original_format": detect_phone_format(raw_phone),
        "normalizable": bool(normalized_phone),
        "masked_normalized": mask_phone(normalized_phone) if normalized_phone else "",
        "original_digits": count_phone_digits(raw_phone),
        "normalized_digits": count_phone_digits(normalized_phone),
    }


def print_report(report: dict[str, object]) -> None:
    print(f"Pedido {report['order_id']}")
    print(f"Metodo de pago: {report['payment_method'] or '-'}")
    print(f"Telefono presente: {'si' if report['phone_present'] else 'no'}")
    print(f"Formato original detectado: {report['original_format']}")
    print(f"Telefono normalizable: {'si' if report['normalizable'] else 'no'}")
    print(
        "Resultado normalizado enmascarado: "
        f"{report['masked_normalized'] or 'no disponible'}"
    )
    print(f"Cantidad de digitos original: {report['original_digits']}")
    print(f"Cantidad de digitos normalizada: {report['normalized_digits']}")


def main() -> None:
    mode, value = parse_args(sys.argv)
    client = WooCommerceClient()

    try:
        if mode == "order":
            orders = [client.get_order(value)]
        else:
            fetched_orders = client.get_orders(per_page=value, page=1)
            if not isinstance(fetched_orders, list):
                raise RuntimeError("WooCommerce no devolvio una lista de pedidos.")
            orders = fetched_orders[:value]
    except WooCommerceAPIError as exc:
        print(str(exc) or "Error consultando WooCommerce.")
        raise SystemExit(1)
    except Exception as exc:
        print(str(exc) or "Error consultando WooCommerce.")
        raise SystemExit(1)

    reports = [build_phone_report(order) for order in orders if isinstance(order, dict)]
    format_counts: dict[str, int] = {}
    with_phone = 0
    normalizable = 0

    for report in reports:
        print_report(report)
        with_phone += 1 if bool(report["phone_present"]) else 0
        normalizable += 1 if bool(report["normalizable"]) else 0
        format_name = str(report["original_format"])
        format_counts[format_name] = format_counts.get(format_name, 0) + 1

    total = len(reports)
    print(f"Pedidos revisados: {total}")
    print(f"Con telefono: {with_phone}")
    print(f"Normalizables: {normalizable}")
    print(f"No normalizables: {total - normalizable}")
    print("Formatos encontrados:")
    for format_name in sorted(format_counts):
        print(f"{format_name}: {format_counts[format_name]}")


if __name__ == "__main__":
    main()
