from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import sys
import time
from datetime import datetime
from pathlib import Path

from services.order_monitor_service import OrderMonitorService


LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "order_monitor.log"
DEFAULT_INTERVAL = 60
DEFAULT_LIMIT = 20
MIN_INTERVAL = 30


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor manual de pedidos WooCommerce en modo simulacion."
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Segundos entre revisiones continuas. Minimo {MIN_INTERVAL}.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Ejecuta una sola revision y finaliza.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Cantidad maxima de pedidos recientes a revisar por ciclo.",
    )
    parser.add_argument(
        "--live-test",
        action="store_true",
        help="Habilita envio automatico de prueba a un telefono controlado.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Habilita envio real a telefonos de facturacion.",
    )
    parser.add_argument(
        "--test-phone",
        type=str,
        help="Telefono de prueba en formato internacional solo digitos.",
    )
    parser.add_argument(
        "--after-order-id",
        type=int,
        help="Procesa solo pedidos con ID mayor a este valor.",
    )
    args = parser.parse_args(argv)

    if args.limit <= 0:
        parser.error("--limit debe ser mayor que 0.")
    if not args.once and args.interval < MIN_INTERVAL:
        parser.error(f"--interval debe ser de al menos {MIN_INTERVAL} segundos.")
    if args.live and args.live_test:
        parser.error("--live y --live-test no pueden usarse al mismo tiempo.")
    if args.live_test:
        if not args.test_phone:
            parser.error("--live-test requiere --test-phone.")
        if not args.after_order_id:
            parser.error("--live-test requiere --after-order-id.")
        if not str(args.test_phone).isdigit():
            parser.error("--test-phone debe contener solo digitos.")
        if int(args.after_order_id) < 0:
            parser.error("--after-order-id debe ser un entero no negativo.")
    elif args.live:
        if not args.after_order_id:
            parser.error("--live requiere --after-order-id.")
        if args.test_phone:
            parser.error("--test-phone no se usa en modo --live.")
        if int(args.after_order_id) < 0:
            parser.error("--after-order-id debe ser un entero no negativo.")
    elif args.test_phone or args.after_order_id:
        parser.error("--test-phone y --after-order-id solo se usan junto con --live-test o --live.")

    return args


def setup_logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("order_monitor")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def timestamp_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_cycle(service: OrderMonitorService, limit: int, logger: logging.Logger) -> bool:
    print(f"[{timestamp_now()}] Revisando pedidos...")
    logger.info("Iniciando ciclo de revision. limit=%s dry_run=True", limit)

    try:
        result = service.scan_recent_orders(limit=limit, dry_run=True)
    except Exception as exc:
        safe_message = str(exc) or "Error desconocido."
        print(f"Error de WooCommerce: {safe_message}")
        logger.error("Fallo en ciclo de revision: %s", safe_message)
        return False

    summary = result["summary"]
    print(
        "Analizados: {analyzed} | simulados: {simulated} | ignorados: {ignored} | "
        "esperando: {waiting} | errores: {errors}".format(**summary)
    )

    changed_items = [item for item in result["results"] if item.get("changed")]
    if changed_items:
        logger.info(
            "Ciclo completado. analyzed=%s simulated=%s ignored=%s waiting=%s errors=%s already_sent=%s changed=%s",
            summary["analyzed"],
            summary["simulated"],
            summary["ignored"],
            summary["waiting"],
            summary["errors"],
            summary["already_sent"],
            len(changed_items),
        )
        for item in changed_items:
            logger.info(
                "Pedido %s | %s | %s | tickets %s/%s",
                item.get("order_id"),
                item.get("status"),
                item.get("summary"),
                item.get("found_tickets", 0),
                item.get("expected_tickets", 0),
            )
    else:
        print("Sin pedidos nuevos o cambios relevantes.")
        logger.info(
            "Ciclo sin cambios relevantes. analyzed=%s simulated=%s ignored=%s waiting=%s errors=%s already_sent=%s",
            summary["analyzed"],
            summary["simulated"],
            summary["ignored"],
            summary["waiting"],
            summary["errors"],
            summary["already_sent"],
        )

    return True


def run_live_test_cycle(
    service: OrderMonitorService,
    limit: int,
    test_phone: str,
    after_order_id: int,
    logger: logging.Logger,
) -> bool:
    print(f"[{timestamp_now()}] Revisando pedidos...")
    logger.info(
        "Iniciando ciclo live-test. limit=%s after_order_id=%s",
        limit,
        after_order_id,
    )

    try:
        result = service.live_test_recent_orders(
            limit=limit,
            test_phone=test_phone,
            after_order_id=after_order_id,
        )
    except Exception as exc:
        safe_message = str(exc) or "Error desconocido."
        print(f"Error de WooCommerce: {safe_message}")
        logger.error("Fallo en ciclo live-test: %s", safe_message)
        return False

    summary = result["summary"]
    print(
        "Analizados: {analyzed} | enviados: {sent} | ignorados: {ignored} | "
        "esperando: {waiting} | errores: {errors} | ya enviados: {already_sent}".format(
            **summary
        )
    )

    changed_items = [item for item in result["results"] if item.get("changed")]
    if changed_items:
        for item in changed_items:
            if item.get("status") in {"sent", "error"} and (
                item.get("billing_phone_present") is not None
            ):
                print(
                    "Telefono de compra presente: "
                    f"{'si' if item.get('billing_phone_present') else 'no'}"
                )
                print(
                    "Telefono normalizable: "
                    f"{'si' if item.get('billing_phone_normalizable') else 'no'}"
                )
                masked_real_destination = str(item.get("masked_real_destination") or "")
                if masked_real_destination:
                    print(f"Destino real detectado: {masked_real_destination}")
                else:
                    print("Destino real detectado: no disponible")
                print("Destino usado: telefono de prueba")

        logger.info(
            "Ciclo live-test completado. analyzed=%s sent=%s ignored=%s waiting=%s errors=%s already_sent=%s changed=%s",
            summary["analyzed"],
            summary["sent"],
            summary["ignored"],
            summary["waiting"],
            summary["errors"],
            summary["already_sent"],
            len(changed_items),
        )
        for item in changed_items:
            logger.info(
                "Pedido %s | %s | %s | tickets %s/%s",
                item.get("order_id"),
                item.get("status"),
                item.get("summary"),
                item.get("found_tickets", 0),
                item.get("expected_tickets", 0),
            )
    else:
        print("Sin pedidos nuevos o cambios relevantes.")
        logger.info(
            "Ciclo live-test sin cambios. analyzed=%s sent=%s ignored=%s waiting=%s errors=%s already_sent=%s",
            summary["analyzed"],
            summary["sent"],
            summary["ignored"],
            summary["waiting"],
            summary["errors"],
            summary["already_sent"],
        )

    return True


def run_live_cycle(
    service: OrderMonitorService,
    limit: int,
    after_order_id: int,
    logger: logging.Logger,
) -> bool:
    print(f"[{timestamp_now()}] Revisando pedidos...")
    logger.info(
        "Iniciando ciclo live. limit=%s after_order_id=%s",
        limit,
        after_order_id,
    )

    try:
        result = service.live_recent_orders(
            limit=limit,
            after_order_id=after_order_id,
        )
    except Exception as exc:
        safe_message = str(exc) or "Error desconocido."
        print(f"Error de WooCommerce: {safe_message}")
        logger.error("Fallo en ciclo live: %s", safe_message)
        return False

    summary = result["summary"]
    print(
        "Analizados: {analyzed} | enviados: {sent} | ignorados: {ignored} | "
        "esperando: {waiting} | errores: {errors} | ya enviados: {already_sent}".format(
            **summary
        )
    )

    changed_items = [item for item in result["results"] if item.get("changed")]
    if changed_items:
        logger.info(
            "Ciclo live completado. analyzed=%s sent=%s ignored=%s waiting=%s errors=%s already_sent=%s changed=%s",
            summary["analyzed"],
            summary["sent"],
            summary["ignored"],
            summary["waiting"],
            summary["errors"],
            summary["already_sent"],
            len(changed_items),
        )
        for item in changed_items:
            masked_destination = str(item.get("masked_destination") or "")
            logger.info(
                "Pedido %s | %s | metodo=%s | tickets %s/%s | enviados=%s | destino=%s",
                item.get("order_id"),
                item.get("status"),
                item.get("payment_method") or "",
                item.get("found_tickets", 0),
                item.get("expected_tickets", 0),
                item.get("sent_tickets", 0),
                masked_destination,
            )
    else:
        print("Sin pedidos nuevos o cambios relevantes.")
        logger.info(
            "Ciclo live sin cambios. analyzed=%s sent=%s ignored=%s waiting=%s errors=%s already_sent=%s",
            summary["analyzed"],
            summary["sent"],
            summary["ignored"],
            summary["waiting"],
            summary["errors"],
            summary["already_sent"],
        )

    return True


def main() -> None:
    args = parse_args(sys.argv[1:])
    logger = setup_logger()
    service = OrderMonitorService()

    if args.live:
        print("MODO REAL DE ENVIO")
        print("Se enviaran tickets a los telefonos de facturacion.")
        print(f"Solo pedidos posteriores a {args.after_order_id}.")
        print("Presione Ctrl+C durante los proximos 10 segundos para cancelar.")
        logger.info(
            "Monitor iniciado en modo live. after_order_id=%s",
            args.after_order_id,
        )
    elif args.live_test:
        print("MODO LIVE TEST")
        print("Los tickets se enviaran al telefono de prueba.")
        print(f"Solo pedidos posteriores a {args.after_order_id}.")
        print("No se usaran telefonos de clientes.")
        logger.info(
            "Monitor iniciado en modo live-test. after_order_id=%s",
            args.after_order_id,
        )
    else:
        logger.info("Monitor iniciado en modo simulacion.")

    try:
        if args.live:
            time.sleep(10)
        while True:
            if args.live:
                run_live_cycle(
                    service,
                    args.limit,
                    int(args.after_order_id),
                    logger,
                )
            elif args.live_test:
                run_live_test_cycle(
                    service,
                    args.limit,
                    str(args.test_phone),
                    int(args.after_order_id),
                    logger,
                )
            else:
                run_cycle(service, args.limit, logger)
            if args.once:
                break
            print(f"Proxima revision en {args.interval} segundos.")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Monitor detenido por el usuario.")
        logger.info("Monitor detenido por Ctrl+C.")


if __name__ == "__main__":
    main()
