from __future__ import annotations

import sys

from services.balance_credit_service import BalanceCreditService


def parse_args(argv: list[str]) -> tuple[int, bool]:
    if len(argv) not in {2, 3} or not str(argv[1]).isdigit():
        raise SystemExit(
            "Uso: python python_backend/test_credit_balance_order.py ORDER_ID [--commit]"
        )
    commit = len(argv) == 3 and argv[2] == "--commit"
    if len(argv) == 3 and not commit:
        raise SystemExit("La unica opcion adicional permitida es --commit.")
    return int(argv[1]), commit


def main() -> None:
    order_id, commit = parse_args(sys.argv)
    service = BalanceCreditService()
    preview = service.preview_credit(order_id)

    if not preview.get("ok"):
        check = preview.get("check") or {}
        print(str(preview.get("message") or "No se puede acreditar el pedido."))
        if check:
            print(f"Order ID: {check.get('order_id', order_id)}")
            print(f"Estado WooCommerce: {check.get('woocommerce_status', '-')}")
            print(f"Metodo de pago: {check.get('payment_method', '-')}")
            print(f"Pagado: {'si' if check.get('paid') else 'no'}")
            print(f"Ya acreditado: {'si' if check.get('credited') else 'no'}")
            print(f"Puede acreditarse: {'si' if check.get('can_credit') else 'no'}")
        raise SystemExit(1)

    print("PEDIDO LISTO PARA ACREDITAR")
    print(f"Order ID: {preview['order_id']}")
    print(f"Cliente: {preview['client_name']}")
    print(f"ID interno: {preview['client_id']}")
    print(f"Importe: {preview['amount']}")
    print(f"Metodo de pago: {preview['payment_method']}")
    print(f"Estado WooCommerce: {preview['woocommerce_status']}")
    print(f"Fecha de pago: {preview['date_paid']}")
    print(f"Referencia: {preview['reference']}")

    balance_preview = preview.get("preview") or {}
    if balance_preview:
        print(f"Saldo anterior: {balance_preview.get('previous_balance')}")
        print(f"Saldo posterior: {balance_preview.get('new_balance')}")

    if not commit:
        print("")
        print("MODO SIMULACION - NO SE ACREDITO SALDO")
        raise SystemExit(0)

    print("")
    first_confirmation = input("Escriba exactamente el ID interno del cliente: ").strip()
    if first_confirmation != str(preview["client_id"]):
        print("Confirmacion incorrecta. No se acredito saldo.")
        raise SystemExit(1)

    second_confirmation = input("Escriba ACREDITAR para confirmar: ").strip()
    if second_confirmation != "ACREDITAR":
        print("Confirmacion final incorrecta. No se acredito saldo.")
        raise SystemExit(1)

    result = service.apply_credit(order_id, int(preview["client_id"]))
    if not result.get("ok"):
        print(str(result.get("message") or "No se pudo acreditar el saldo."))
        raise SystemExit(1)

    print("")
    print("SALDO ACREDITADO")
    print(f"Order ID: {result['order_id']}")
    print(f"Referencia: {result['reference']}")
    print(f"Saldo anterior: {result['previous_balance']}")
    print(f"Importe: {result['amount']}")
    print(f"Saldo nuevo: {result['new_balance']}")
    print(f"Recarga ID: {result['recarga_id']}")
    print(f"Historial ID: {result['historial_id']}")
    print(f"Fecha usada: {result['date_used']}")

    verification = result.get("verification") or {}
    if verification.get("ok"):
        print("")
        print("VERIFICACION FINAL")
        print(f"Saldo en clientes: {verification.get('client_balance')}")
        recarga = verification.get("recarga_row") or {}
        historial = verification.get("historial_row") or {}
        print(
            "Recarga: "
            f"ID={recarga.get('Rec_indice')} | Caja={recarga.get('Rec_Numcaja')} | "
            f"Tipo={recarga.get('Rec_TipoPago')} | Importe={recarga.get('Rec_Importe')}"
        )
        print(
            "Historial: "
            f"ID={historial.get('Hist_Indice')} | Caja={historial.get('Hist_Caja')} | "
            f"Articulo={historial.get('Hist_ID_ART')} | Total={historial.get('Hist_Total')}"
        )

    if result.get("woocommerce_note_error"):
        print("")
        print("Aviso: la acreditacion fue correcta, pero no se pudo agregar la nota en WooCommerce.")


if __name__ == "__main__":
    main()
