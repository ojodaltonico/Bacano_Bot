from __future__ import annotations

import sys

from services.balance_order_service import BalanceOrderService


def parse_args(argv: list[str]) -> dict[str, str | bool]:
    if len(argv) not in {5, 6}:
        raise SystemExit(
            "Uso: python python_backend/test_create_balance_order.py DNI IMPORTE EMAIL TELEFONO | "
            "python python_backend/test_create_balance_order.py DNI IMPORTE EMAIL TELEFONO --commit"
        )

    dni = str(argv[1]).strip()
    amount = str(argv[2]).strip()
    email = str(argv[3]).strip()
    phone = str(argv[4]).strip()
    commit = len(argv) == 6 and argv[5] == "--commit"

    if len(argv) == 6 and not commit:
        raise SystemExit(
            "La unica opcion adicional permitida es --commit."
        )

    return {
        "dni": dni,
        "amount": amount,
        "email": email,
        "phone": phone,
        "commit": commit,
    }


def print_preview(preview: dict[str, object], simulation: bool) -> None:
    print(f"Cliente: {preview['name']}")
    print(f"DNI: {preview['dni_masked']}")
    print(f"ID interno: {preview['client_id']}")
    print(f"Importe: {preview['amount_display']}")
    print(f"Correo: {preview['email']}")
    print(f"Telefono: {preview['phone_masked']}")
    if simulation:
        print("MODO SIMULACION - NO SE CREO NINGUN PEDIDO")


def main() -> None:
    options = parse_args(sys.argv)
    service = BalanceOrderService()

    try:
        preview = service.preview_order(
            str(options["dni"]),
            str(options["amount"]),
            str(options["email"]),
            str(options["phone"]),
        )
    except Exception as exc:
        print(str(exc) or "No se pudo preparar la vista previa.")
        raise SystemExit(1)

    if not preview.get("ok"):
        print(str(preview.get("message") or "No se pudo preparar la vista previa."))
        if preview.get("client_ids"):
            print(
                "IDs encontrados: "
                + ", ".join(str(item) for item in preview.get("client_ids", []))
            )
        raise SystemExit(1)

    print_preview(preview, simulation=not bool(options["commit"]))
    if not options["commit"]:
        raise SystemExit(0)

    print("")
    first_confirmation = input("Escriba exactamente el ID interno del cliente: ").strip()
    if first_confirmation != str(preview["client_id"]):
        print("Confirmacion incorrecta. No se creo ningun pedido.")
        raise SystemExit(1)

    second_confirmation = input("Escriba CREAR para confirmar: ").strip()
    if second_confirmation != "CREAR":
        print("Confirmacion final incorrecta. No se creo ningun pedido.")
        raise SystemExit(1)

    result = service.create_order(
        str(options["dni"]),
        str(options["amount"]),
        str(options["email"]),
        str(options["phone"]),
        int(preview["client_id"]),
    )
    if not result.get("ok"):
        print(str(result.get("message") or "No se pudo crear el pedido."))
        raise SystemExit(1)

    print("PEDIDO CREADO")
    print(f"Order ID: {result['order_id']}")
    print(f"Estado: {result['status']}")
    print(f"Importe: {result['amount']}")
    print(f"Cliente: {result['client_name']}")
    print(f"URL de pago: {result['payment_url']}")


if __name__ == "__main__":
    main()
