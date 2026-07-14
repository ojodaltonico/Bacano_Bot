from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

from services.ticket_delivery_service import TicketDeliveryService


DEBUG_DIR = Path(__file__).resolve().parent / "debug"
ENDPOINT_URL = "http://127.0.0.1:3000/internal/send-document"
REQUEST_TIMEOUT = 30


def parse_args(argv: list[str]) -> tuple[int, str]:
    if len(argv) != 3:
        raise SystemExit(
            "Uso: python python_backend/test_full_ticket_delivery.py ORDER_ID TELEFONO_PRUEBA"
        )

    order_id_raw = argv[1].strip()
    phone = argv[2].strip()

    if not order_id_raw.isdigit():
        raise SystemExit("El ORDER_ID debe ser numerico.")
    if not phone.isdigit():
        raise SystemExit("El telefono de prueba debe ser numerico.")

    return int(order_id_raw), phone


def build_caption(ticket_pdf: dict[str, str], index: int, total: int) -> str:
    lines = ["🎟️ Entrada Bacano"]

    event_name = str(ticket_pdf.get("event_name") or "").strip()
    ticket_type = str(ticket_pdf.get("ticket_type") or "").strip()

    if event_name:
        lines.append(f"Evento: {event_name}")
    if ticket_type:
        lines.append(f"Tipo: {ticket_type}")

    lines.append(f"Entrada {index} de {total}")
    return "\n".join(lines)


def send_pdf(phone: str, pdf_path: Path, filename: str, caption: str) -> tuple[bool, str]:
    payload = {
        "phone": phone,
        "file_path": str(pdf_path),
        "filename": filename,
        "caption": caption,
    }

    try:
        response = requests.post(
            ENDPOINT_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        return False, "El bot principal debe estar encendido y escuchando en http://127.0.0.1:3000."

    try:
        data = response.json()
    except ValueError:
        return False, "El bot principal devolvio una respuesta no JSON."

    if response.ok and data.get("ok"):
        return True, "Documento enviado"

    detail = data.get("detail")
    error = data.get("error") or "Error desconocido"
    return False, detail or error


def main() -> None:
    order_id, phone_override = parse_args(sys.argv)
    service = TicketDeliveryService()

    destination_dir = DEBUG_DIR / f"delivery_test_{order_id}"
    result = service.prepare_order_tickets(order_id, destination_dir)

    print(f"Pedido listo: {'si' if result.get('ready') else 'no'}")

    if not result.get("ready"):
        print(f"Motivo: {result.get('reason') or 'No disponible'}")
        print(f"Estado: {result.get('status') or 'N/A'}")
        print(f"Metodo de pago: {result.get('payment_method') or 'N/A'}")
        print(
            f"Fecha de pago presente: {'si' if bool(result.get('date_paid')) else 'no'}"
        )
        print(
            f"Necesita pago: {'si' if bool(result.get('needs_payment')) else 'no'}"
        )
        print(
            f"Telefono presente: {'si' if bool(result.get('billing_phone_present')) else 'no'}"
        )
        raise SystemExit(1)

    ticket_pdfs = result.get("ticket_pdfs")
    if not ticket_pdfs:
        ticket_pdfs = [
            {
                "transaction_id": "",
                "ticket_type": "",
                "event_name": "",
                "pdf_path": pdf_file,
            }
            for pdf_file in (result.get("pdf_files") or [])
        ]

    expected_tickets = int(result.get("expected_tickets") or 0)
    downloaded_count = len(ticket_pdfs)
    sent_count = 0

    print(f"Cantidad esperada: {expected_tickets}")
    print(f"Cantidad descargada: {downloaded_count}")

    total = len(ticket_pdfs)
    for index, ticket_pdf in enumerate(ticket_pdfs, start=1):
        pdf_path = Path(ticket_pdf["pdf_path"])
        filename = pdf_path.name
        caption = build_caption(ticket_pdf, index, total)
        ok, message = send_pdf(phone_override, pdf_path, filename, caption)
        if ok:
            sent_count += 1
            print(f"PDF {index}/{total}: enviado | archivo={filename}")
        else:
            print(f"PDF {index}/{total}: error | archivo={filename} | detalle={message}")

        if index < total:
            time.sleep(1)

    print(f"Cantidad enviada: {sent_count}")
    if sent_count == total:
        print("Resumen final: envio completo")
    else:
        print("Resumen final: envio incompleto")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
