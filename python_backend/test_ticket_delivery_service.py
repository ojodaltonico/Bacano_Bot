from __future__ import annotations

import sys
from pathlib import Path

from services.ticket_delivery_service import TicketDeliveryService


DEBUG_DIR = Path(__file__).resolve().parent / "debug"


def parse_order_id(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit(
            "Uso: python python_backend/test_ticket_delivery_service.py <woocommerce_order_id>"
        )

    raw_value = argv[1].strip()
    if not raw_value.isdigit():
        raise SystemExit("El ID del pedido WooCommerce debe ser numerico.")

    return int(raw_value)


def main() -> None:
    order_id = parse_order_id(sys.argv)
    service = TicketDeliveryService()
    delivery_info = service.get_order_delivery_info(order_id)

    destination_dir = DEBUG_DIR / f"delivery_test_{order_id}"
    result = service.prepare_order_tickets(order_id, destination_dir)

    print(f"Pedido listo: {'si' if result.get('ready') else 'no'}")
    print(f"Metodo de pago: {delivery_info.get('payment_method') or 'N/A'}")
    print(
        f"Telefono presente: {'si' if bool(delivery_info.get('billing_phone')) else 'no'}"
    )
    print(f"Tickets esperados: {delivery_info.get('expected_tickets', 0)}")
    print(
        f"Tickets encontrados: {result.get('found_tickets', 0) if result.get('ready') else 0}"
    )

    pdf_files = result.get("pdf_files") if result.get("ready") else []
    pdf_files = pdf_files or []
    print(f"Cantidad de PDFs descargados: {len(pdf_files)}")
    for ticket_pdf in result.get("ticket_pdfs", []) if result.get("ready") else []:
        pdf_name = Path(ticket_pdf["pdf_path"]).name
        holder_source = ticket_pdf.get("holder_source") or "fallback"
        holder_found = "si" if holder_source != "fallback" else "no"
        print(
            f"Archivo generado: {pdf_name} | transaction_id={ticket_pdf['transaction_id']} | "
            f"Titular encontrado: {holder_found} | Fuente del titular: {holder_source}"
        )
        print(
            f"Claves ticket recibido: {ticket_pdf.get('raw_ticket_keys', [])} | "
            f"Claves ticket normalizado: {ticket_pdf.get('normalized_ticket_keys', [])}"
        )
        print(
            f"buyer_first={ticket_pdf.get('buyer_first_debug', '')} | "
            f"buyer_last={ticket_pdf.get('buyer_last_debug', '')} | "
            f"Buyer Name={ticket_pdf.get('buyer_name_custom_field_debug', '')}"
        )


if __name__ == "__main__":
    main()
