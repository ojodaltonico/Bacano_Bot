from __future__ import annotations

import sys

from services.order_monitor_service import OrderMonitorService


def parse_args(argv: list[str]) -> tuple[str, dict[str, int | str | bool]]:
    if len(argv) == 1:
        return "scan", {"limit": 20}

    if len(argv) == 3 and argv[1] == "--limit" and argv[2].isdigit():
        return "scan", {"limit": int(argv[2])}

    if len(argv) in {5, 6} and argv[1] == "--send-order":
        order_id = argv[2].strip()
        if not order_id.isdigit():
            raise SystemExit("El valor de --send-order debe ser numerico.")

        if argv[3] != "--test-phone":
            raise SystemExit("Debes indicar --test-phone cuando usas --send-order.")

        test_phone = argv[4].strip()
        if not test_phone.isdigit():
            raise SystemExit("El valor de --test-phone debe ser numerico.")

        force = False
        if len(argv) == 6:
            if argv[5] != "--force":
                raise SystemExit("La unica opcion adicional permitida es --force.")
            force = True

        return "send", {
            "order_id": int(order_id),
            "test_phone": test_phone,
            "force": force,
        }

    raise SystemExit(
        "Uso: python python_backend/test_order_monitor.py [--limit 50] | "
        "python python_backend/test_order_monitor.py --send-order 39147 --test-phone 549XXXXXXXXXX [--force]"
    )


def main() -> None:
    mode, options = parse_args(sys.argv)
    service = OrderMonitorService()

    if mode == "send":
        result = service.send_order_for_test(
            int(options["order_id"]),
            str(options["test_phone"]),
            bool(options["force"]),
        )
        if result.get("already_sent"):
            print(f"Pedido {result['order_id']} ya fue enviado. No se repite.")
            raise SystemExit(0)

        print(f"Pedido {result['order_id']}")
        print(f"Listo: {'si' if result.get('ready') else 'no'}")
        print(
            f"Tickets: {result.get('found_tickets', 0)}/{result.get('expected_tickets', 0)}"
        )
        print("Telefono usado: prueba")

        for item in result.get("results", []):
            if item.get("ok"):
                print(f"PDF {item['index']}/{len(result['results'])}: enviado")
            else:
                print(f"PDF {item['index']}/{len(result['results'])}: error")

        if result.get("ok"):
            print(f"Estado guardado: {result.get('state_saved')}")
            raise SystemExit(0)

        print(f"Estado guardado: {result.get('state_saved', 'error')}")
        print(f"Motivo: {result.get('reason') or 'Error desconocido'}")
        raise SystemExit(1)

    result = service.scan_recent_orders(limit=int(options["limit"]), dry_run=True)

    for item in result["results"]:
        status = item["status"]
        order_id = item["order_id"]
        summary = item["summary"]
        if status == "simulated":
            print(
                f"Pedido {order_id} | simulated | {summary} | "
                f"tickets {item['found_tickets']}/{item['expected_tickets']} | "
                f"telefono valido={'si' if item['phone_valid'] else 'no'}"
            )
        elif status == "waiting":
            print(f"Pedido {order_id} | waiting | {summary}")
        elif status == "ignored":
            print(f"Pedido {order_id} | ignored | {summary}")
        elif status == "already_sent":
            print(f"Pedido {order_id} | already_sent | {summary}")
        else:
            print(f"Pedido {order_id} | error | {summary}")

    summary = result["summary"]
    print(f"Analizados: {summary['analyzed']}")
    print(f"Listos simulados: {summary['simulated']}")
    print(f"En espera: {summary['waiting']}")
    print(f"Ignorados: {summary['ignored']}")
    print(f"Errores: {summary['errors']}")
    print(f"Ya enviados: {summary['already_sent']}")


if __name__ == "__main__":
    main()
