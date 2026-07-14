from __future__ import annotations

import sys

from services.balance_load_service import BalanceLoadService


def mask_dni(dni: str) -> str:
    digits = "".join(char for char in str(dni or "") if char.isdigit())
    if len(digits) <= 2:
        return "*" * len(digits)
    if len(digits) <= 4:
        return "*" * (len(digits) - 2) + digits[-2:]
    return "*" * (len(digits) - 4) + digits[-4:]


def parse_args(argv: list[str]) -> dict[str, str | bool]:
    if len(argv) not in {3, 6}:
        raise SystemExit(
            "Uso: python python_backend/test_apply_balance_load.py DNI IMPORTE | "
            "python python_backend/test_apply_balance_load.py DNI IMPORTE --commit --reference TEST-LOAD-20260714-001"
        )

    dni = str(argv[1]).strip()
    amount = str(argv[2]).strip()
    if not dni.isdigit():
        raise SystemExit("El DNI debe ser numerico.")

    options: dict[str, str | bool] = {
        "dni": dni,
        "amount": amount,
        "commit": False,
        "reference": "",
    }

    if len(argv) == 6:
        if argv[3] != "--commit" or argv[4] != "--reference":
            raise SystemExit(
                "Uso real: python python_backend/test_apply_balance_load.py DNI IMPORTE --commit --reference TEST-LOAD-20260714-001"
            )
        options["commit"] = True
        options["reference"] = str(argv[5]).strip()

    return options


def print_preview(preview: dict[str, object], dni: str, simulation: bool) -> None:
    print(f"DNI: {mask_dni(dni)}")
    print(f"Cliente: {preview['name']}")
    print(f"ID interno: {preview['client_id']}")
    print(f"Saldo anterior: {preview['previous_balance']}")
    print(f"Importe: {preview['amount']}")
    print(f"Saldo nuevo: {preview['new_balance']}")
    print(f"Bloqueado: {preview['blocked']}")
    print(f"Tarjeta activa: {preview['active_card']}")
    if simulation:
        print("MODO SIMULACION - NO SE ESCRIBIO NADA")


def main() -> None:
    options = parse_args(sys.argv)
    service = BalanceLoadService()

    preview = service.preview_load(str(options["dni"]), str(options["amount"]))
    if not preview.get("can_apply"):
        print(str(preview.get("message") or "No se puede aplicar la carga."))
        if preview.get("client_ids"):
            print(
                "IDs encontrados: "
                + ", ".join(str(item) for item in preview.get("client_ids", []))
            )
        raise SystemExit(1)

    print_preview(preview, str(options["dni"]), simulation=not bool(options["commit"]))
    if not options["commit"]:
        raise SystemExit(0)

    print("")
    confirmation = input("Escriba exactamente el ID interno del cliente para confirmar: ").strip()
    if confirmation != str(preview["client_id"]):
        print("Confirmacion incorrecta. No se escribio nada.")
        raise SystemExit(1)

    second_confirmation = input("Escriba CARGAR para ejecutar la transaccion: ").strip()
    if second_confirmation != "CARGAR":
        print("Confirmacion final incorrecta. No se escribio nada.")
        raise SystemExit(1)

    result = service.apply_load(
        str(options["dni"]),
        str(options["amount"]),
        str(options["reference"]),
        int(preview["client_id"]),
    )
    if not result.get("ok"):
        print(str(result.get("message") or "No se pudo aplicar la carga."))
        raise SystemExit(1)

    verification = service.verify_applied_load(
        int(result["client_id"]),
        int(result["recarga_id"]),
        int(result["historial_id"]),
    )

    print("")
    print("CARGA APLICADA")
    print(f"Cliente: {result['name']}")
    print(f"DNI: {mask_dni(str(options['dni']))}")
    print(f"ID interno: {result['client_id']}")
    print(f"Saldo anterior: {result['previous_balance']}")
    print(f"Importe: {result['amount']}")
    print(f"Saldo nuevo: {result['new_balance']}")
    print(f"Fecha usada: {result['date_used']}")
    print(f"Referencia: {result['reference']}")
    print(f"Recarga ID: {result['recarga_id']}")
    print(f"Historial ID: {result['historial_id']}")

    print("")
    print("Verificacion final:")
    if verification.get("ok"):
        print(f"Saldo en clientes: {verification.get('client_balance')}")
        recarga_row = verification.get("recarga_row") or {}
        historial_row = verification.get("historial_row") or {}
        print(
            "Fila recargas: "
            f"Rec_indice={recarga_row.get('Rec_indice')} | "
            f"Rec_IdCli={recarga_row.get('Rec_IdCli')} | "
            f"Rec_Numcaja={recarga_row.get('Rec_Numcaja')} | "
            f"Rec_TipoPago={recarga_row.get('Rec_TipoPago')} | "
            f"Rec_Importe={recarga_row.get('Rec_Importe')}"
        )
        print(
            "Fila historial: "
            f"Hist_Indice={historial_row.get('Hist_Indice')} | "
            f"Hist_Id={historial_row.get('Hist_Id')} | "
            f"Hist_Caja={historial_row.get('Hist_Caja')} | "
            f"Hist_ID_ART={historial_row.get('Hist_ID_ART')} | "
            f"Hist_Total={historial_row.get('Hist_Total')}"
        )
    else:
        print(str(verification.get("message") or "No se pudo verificar la carga."))


if __name__ == "__main__":
    main()
