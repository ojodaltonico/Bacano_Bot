from __future__ import annotations

import json
import sys

from services.balance_payment_service import BalancePaymentService


def parse_args(argv: list[str]) -> int:
    if len(argv) != 2 or not str(argv[1]).isdigit():
        raise SystemExit(
            "Uso: python python_backend/test_check_balance_order.py ORDER_ID"
        )
    return int(argv[1])


def main() -> None:
    order_id = parse_args(sys.argv)
    service = BalancePaymentService()
    result = service.check_order(order_id)

    if not result.get("ok"):
        print(str(result.get("message") or "No se pudo verificar el pedido."))
        diagnostics = result.get("tickera_diagnostics")
        if diagnostics:
            print("")
            print("Diagnostico Tickera:")
            print(json.dumps(diagnostics, ensure_ascii=False, default=str, indent=2))
        raise SystemExit(1)

    print("PEDIDO DE CARGA")
    print(f"Order ID: {result['order_id']}")
    print(f"Estado WooCommerce: {result['woocommerce_status']}")
    print(f"Fecha de pago: {result['date_paid']}")
    print(f"Método de pago: {result['payment_method'] or '-'}")
    print(f"Cliente interno: {result['client_id']}")
    print(f"Importe: {result['amount']}")
    print(f"Estado local: {result['local_status']}")
    print(f"Contiene Tickera: {'si' if result.get('contains_tickera') else 'no'}")
    print(f"Pagado: {'si' if result['paid'] else 'no'}")
    print(f"Ya acreditado: {'si' if result['credited'] else 'no'}")
    print(f"Puede acreditarse: {'si' if result['can_credit'] else 'no'}")
    print(f"Motivo: {result['reason'] or '-'}")

    if result.get("preview"):
        preview = result["preview"]
        print("")
        print(f"Saldo anterior: {preview['previous_balance']}")
        print(f"Importe: {preview['amount']}")
        print(f"Saldo posterior: {preview['new_balance']}")
        print("")
        print("VISTA PREVIA - NO SE ACREDITO SALDO")


if __name__ == "__main__":
    main()
