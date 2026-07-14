from __future__ import annotations

import sys
from pathlib import Path

import requests


ENDPOINT_URL = "http://127.0.0.1:3000/internal/send-document"
REQUEST_TIMEOUT = 30
CAPTION = "🎟️ Entrada Bacano"


def parse_args(argv: list[str]) -> tuple[str, Path]:
    if len(argv) != 3:
        raise SystemExit(
            'Uso: python python_backend/test_send_ticket_via_bot.py 549XXXXXXXXXX "ruta_del_pdf"'
        )

    phone = argv[1].strip()
    pdf_path = Path(argv[2]).expanduser().resolve()

    if not phone.isdigit():
        raise SystemExit("El telefono debe contener solamente digitos.")

    return phone, pdf_path


def main() -> None:
    phone, pdf_path = parse_args(sys.argv)
    payload = {
        "phone": phone,
        "file_path": str(pdf_path),
        "filename": pdf_path.name,
        "caption": CAPTION,
    }

    try:
        response = requests.post(
            ENDPOINT_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise SystemExit(f"Error: {exc}") from exc

    try:
        data = response.json()
    except ValueError:
        raise SystemExit("Error: respuesta no JSON del bot.") from None

    if response.ok and data.get("ok"):
        print("Exito: documento enviado")
        return

    print(f"Error: {data.get('error') or 'Error desconocido'}")


if __name__ == "__main__":
    main()
