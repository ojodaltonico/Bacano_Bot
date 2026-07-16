from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

from services.balance_monitor_service import BalanceMonitorService
from services.balance_settings_service import BalanceSettingsService


DEFAULT_INTERVAL = 60
DEFAULT_LIMIT = 50
MIN_INTERVAL = 30


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor automatico de cargas de saldo pagadas en WooCommerce."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Simula sin acreditar (modo predeterminado).")
    mode.add_argument("--live", action="store_true", help="Acredita pedidos validos; requiere un limite inicial.")
    mode.add_argument(
        "--use-settings",
        action="store_true",
        help="Usa los controles operativos guardados por la GUI.",
    )
    parser.add_argument("--once", action="store_true", help="Ejecuta una sola pasada y termina.")
    parser.add_argument("--after-order-id", type=int, help="Procesa solo IDs mayores al indicado.")
    parser.add_argument("--after-date", help="Procesa pedidos posteriores a una fecha ISO 8601 con zona horaria.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Pedidos recientes a consultar (1-100).")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Segundos entre pasadas en modo loop.")
    args = parser.parse_args(argv)

    if args.limit < 1 or args.limit > 100:
        parser.error("--limit debe estar entre 1 y 100.")
    if args.after_order_id is not None and args.after_order_id < 0:
        parser.error("--after-order-id debe ser un entero no negativo.")
    if args.after_date:
        try:
            args.after_date = BalanceMonitorService.validate_after_date(args.after_date)
        except ValueError as exc:
            parser.error(str(exc))
    if args.live and args.after_order_id is None and not args.after_date:
        parser.error("--live requiere --after-order-id o --after-date.")
    if args.use_settings and (args.after_order_id is not None or args.after_date):
        parser.error("--use-settings toma los limites desde SQLite.")
    if not args.once and args.interval < MIN_INTERVAL:
        parser.error(f"--interval debe ser de al menos {MIN_INTERVAL} segundos.")
    return args


def run_cycle(service: BalanceMonitorService, args: argparse.Namespace) -> bool:
    mode = "CONFIGURADO" if args.use_settings else ("LIVE" if args.live else "DRY-RUN")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Monitor de saldo | {mode}")
    try:
        if args.use_settings:
            result = service.scan_configured_orders(limit=int(args.limit))
        else:
            result = service.scan_recent_orders(
                live=bool(args.live),
                limit=int(args.limit),
                after_order_id=args.after_order_id,
                after_date=args.after_date,
            )
    except Exception as exc:
        print(f"ERROR DEL MONITOR: {exc}")
        return False

    summary = result["summary"]
    print(
        "Analizados: {analyzed} | acreditaria: {would_credit} | acreditados: {credited} | "
        "ignorados: {ignored} | esperando: {waiting} | errores: {errors}".format(**summary)
    )
    for item in result["results"]:
        print(json.dumps(item, ensure_ascii=False, default=str))
    if not result["results"]:
        print("Sin pedidos Bacano de carga de saldo dentro de los filtros.")
    return summary["errors"] == 0


def main() -> None:
    args = parse_args(sys.argv[1:])
    service = BalanceMonitorService()
    settings_service = BalanceSettingsService() if args.use_settings else None
    try:
        while True:
            run_cycle(service, args)
            if args.once:
                break
            interval = (
                int(settings_service.get_settings()["monitor_interval"])
                if settings_service
                else args.interval
            )
            print(f"Proxima revision en {interval} segundos.")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Monitor detenido por el usuario.")


if __name__ == "__main__":
    main()
