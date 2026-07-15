from __future__ import annotations

import sys

from services.balance_order_service import BalanceOrderService


def parse_args(argv: list[str]) -> dict[str, str | bool | None]:
    args = list(argv[1:])
    commit = False
    if args and args[-1] == "--commit":
        commit = True
        args = args[:-1]

    if len(args) == 3:
        dni, amount, phone = args
        email = None
    elif len(args) == 4:
        # Compatibilidad temporal con la forma anterior:
        # DNI IMPORTE EMAIL TELEFONO
        dni, amount, email, phone = args
    else:
        raise SystemExit(
            "Uso: python python_backend/test_create_balance_order.py DNI IMPORTE TELEFONO [--commit]\n"
            "Compatibilidad: python python_backend/test_create_balance_order.py DNI IMPORTE EMAIL TELEFONO [--commit]"
        )

    return {
        "dni": str(dni).strip(),
        "amount": str(amount).strip(),
        "email": str(email).strip() if email else None,
        "phone": str(phone).strip(),
        "commit": commit,
    }


def print_preview(preview: dict[str, object], simulation: bool) -> None:
    print(f"Cliente: {preview['name']}")
    print(f"DNI: {preview['dni_masked']}")
    print(f"ID interno: {preview['client_id']}")
    print(f"Importe: {preview['amount_display']}")
    if preview.get("email"):
        print(f"Correo: {preview['email']}")
    else:
        print("Correo: no informado (pedido invitado)")
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
            str(options["phone"]),
            email=str(options["email"]) if options["email"] else None,
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
        str(options["phone"]),
        int(preview["client_id"]),
        email=str(options["email"]) if options["email"] else None,
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
