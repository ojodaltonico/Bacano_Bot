from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import sys
from typing import Any

import mysql.connector
from mysql.connector import Error

from config_manager import load_config


MIN_AMOUNT = Decimal("1000")
MAX_AMOUNT = Decimal("500000")
TWOPLACES = Decimal("0.01")


def connect_read_only():
    config = load_config()
    db_config = config.get("database", {})
    required = ("host", "user", "password", "database")
    missing = [key for key in required if not str(db_config.get(key) or "").strip()]
    if missing:
        raise RuntimeError(
            "Faltan campos requeridos en 'database': " + ", ".join(missing)
        )

    return mysql.connector.connect(
        host=db_config["host"],
        user=db_config["user"],
        password=db_config["password"],
        database=db_config["database"],
        charset="utf8",
        use_unicode=True,
        collation="utf8_general_ci",
        autocommit=True,
    )


def fetch_all_dict(cursor, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor.execute(query, params)
    return list(cursor.fetchall())


def fetch_one_dict(cursor, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    cursor.execute(query, params)
    return cursor.fetchone()


def get_clientes_columns(cursor) -> list[str]:
    rows = fetch_all_dict(
        cursor,
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'clientes'
        ORDER BY ORDINAL_POSITION
        """,
    )
    return [row["COLUMN_NAME"] for row in rows]


def mask_dni(dni: str) -> str:
    digits = "".join(char for char in str(dni or "") if char.isdigit())
    if len(digits) <= 2:
        return "*" * len(digits)
    if len(digits) <= 4:
        return "*" * (len(digits) - 2) + digits[-2:]
    return "*" * (len(digits) - 4) + digits[-4:]


def parse_argentine_amount(value: Any) -> Decimal:
    raw = str(value or "").strip()
    if not raw:
        return Decimal("0.00")

    sanitized = raw.replace(" ", "")
    if "," in sanitized:
        sanitized = sanitized.replace(".", "").replace(",", ".")
    elif "." in sanitized:
        parts = sanitized.split(".")
        if len(parts) > 2:
            sanitized = "".join(parts)
        elif len(parts) == 2 and len(parts[1]) == 3:
            sanitized = "".join(parts)

    try:
        amount = Decimal(sanitized)
    except InvalidOperation as exc:
        raise RuntimeError(f"Importe invalido: {value}") from exc

    return amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def validate_requested_amount(amount_text: str) -> Decimal:
    amount = parse_argentine_amount(amount_text)
    if amount <= 0:
        raise RuntimeError("El importe debe ser positivo.")
    if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
        raise RuntimeError("El importe debe estar entre $1.000 y $500.000.")

    normalized_input = str(amount_text).strip().replace(" ", "")
    if "," in normalized_input:
        decimal_part = normalized_input.split(",")[-1]
        if len(decimal_part) > 2:
            raise RuntimeError("El importe no puede tener mas de dos decimales.")
    elif normalized_input.count(".") == 1:
        integer_part, decimal_part = normalized_input.split(".")
        if decimal_part and len(decimal_part) not in {3} and len(decimal_part) > 2:
            raise RuntimeError("El importe no puede tener mas de dos decimales.")
        if not re.fullmatch(r"\d+", integer_part):
            raise RuntimeError("El importe no es numerico.")

    return amount


def format_argentine_amount(amount: Decimal) -> str:
    normalized = amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    sign = "-" if normalized < 0 else ""
    normalized = abs(normalized)
    integer_part, decimal_part = f"{normalized:.2f}".split(".")
    chunks = []
    while integer_part:
        chunks.append(integer_part[-3:])
        integer_part = integer_part[:-3]
    formatted_integer = ".".join(reversed(chunks)) if chunks else "0"
    return f"{sign}{formatted_integer},{decimal_part}"


def find_optional_columns(columns: list[str]) -> dict[str, str | None]:
    lowered = {column.lower(): column for column in columns}

    def find_by_keywords(*keywords: str) -> str | None:
        for column in columns:
            lowered_name = column.lower()
            if all(keyword in lowered_name for keyword in keywords):
                return column
        for keyword in keywords:
            for lowered_name, original in lowered.items():
                if keyword in lowered_name:
                    return original
        return None

    return {
        "blocked": find_by_keywords("bloq"),
        "active_card": find_by_keywords("tj", "act"),
    }


def get_client_candidates(cursor, dni: str, optional_columns: dict[str, str | None]) -> list[dict[str, Any]]:
    selected_columns = ["Cli_Indice", "Cli_DNI", "Cli_Adelantos"]
    for key in ("blocked", "active_card"):
        column = optional_columns.get(key)
        if column and column not in selected_columns:
            selected_columns.append(column)

    query = (
        "SELECT "
        + ", ".join(f"`{column}`" for column in selected_columns)
        + " FROM `clientes` WHERE `Cli_DNI` = %s"
    )
    return fetch_all_dict(cursor, query, (dni,))


def get_recent_recargas(cursor, limit: int = 5) -> list[dict[str, Any]]:
    return fetch_all_dict(
        cursor,
        """
        SELECT `Rec_Fecha`, `Rec_IdCli`, `Rec_Numcaja`, `Rec_TipoPago`, `Rec_Importe`
        FROM `recargas`
        ORDER BY `Rec_Fecha` DESC
        LIMIT %s
        """,
        (limit,),
    )


def parse_db_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def describe_date_offset(recent_recargas: list[dict[str, Any]]) -> dict[str, Any]:
    latest_raw = recent_recargas[0]["Rec_Fecha"] if recent_recargas else None
    latest_dt = parse_db_datetime(latest_raw)
    now_dt = datetime.now()
    if latest_dt is None:
        return {
            "latest_recarga_date": str(latest_raw or ""),
            "server_now": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "difference_days": None,
            "difference_years_approx": None,
            "note": "No se pudo interpretar la fecha mas reciente de recargas.",
        }

    delta = latest_dt - now_dt
    difference_days = delta.days
    difference_years = round(delta.days / 365.25, 1)
    return {
        "latest_recarga_date": latest_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "server_now": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "difference_days": difference_days,
        "difference_years_approx": difference_years,
        "note": "No se selecciono automaticamente una estrategia de fecha.",
    }


def print_plan(client_id: int, formatted_new_balance: str, formatted_amount: str) -> None:
    print("Plan de escritura:")
    print("UPDATE clientes")
    print(f"SET Cli_Adelantos = {formatted_new_balance}")
    print(f"WHERE Cli_Indice = {client_id}")
    print("")
    print("INSERT recargas")
    print("Rec_Fecha = ...")
    print(f"Rec_IdCli = {client_id}")
    print("Rec_Numcaja = BOT")
    print("Rec_TipoPago = MERCADO PAGO")
    print(f"Rec_Importe = {formatted_amount}")
    print("")
    print("INSERT historial")
    print("Hist_Fecha = ...")
    print(f"Hist_Id = {client_id}")
    print("Hist_Caja = BOT")
    print("Hist_ID_ART = RECARGA")
    print("Hist_Detalle = RECARGA MERCADO PAGO BOT")
    print("Hist_Cant = -")
    print("Hist_Unitario = -")
    print(f"Hist_Total = {formatted_amount}")


def main() -> None:
    if len(sys.argv) != 3:
        print(
            "Uso: python python_backend/test_simulate_balance_load.py DNI IMPORTE"
        )
        raise SystemExit(1)

    dni = str(sys.argv[1]).strip()
    amount_text = str(sys.argv[2]).strip()
    if not dni.isdigit():
        print("El DNI debe ser numerico.")
        raise SystemExit(1)

    connection = None
    cursor = None
    try:
        requested_amount = validate_requested_amount(amount_text)
        connection = connect_read_only()
        cursor = connection.cursor(dictionary=True)

        clientes_columns = get_clientes_columns(cursor)
        optional_columns = find_optional_columns(clientes_columns)
        candidates = get_client_candidates(cursor, dni, optional_columns)

        print("SIMULACION - NO SE ESCRIBIO NADA")
        print(f"DNI consultado: {mask_dni(dni)}")

        if not candidates:
            print("Error: no existe un cliente con ese DNI.")
            raise SystemExit(1)

        if len(candidates) > 1:
            ids = ", ".join(str(row["Cli_Indice"]) for row in candidates)
            print("Error: existen varios clientes con ese DNI.")
            print(f"IDs encontrados: {ids}")
            raise SystemExit(1)

        client = candidates[0]
        client_id = int(client["Cli_Indice"])
        previous_balance = parse_argentine_amount(client.get("Cli_Adelantos"))
        new_balance = previous_balance + requested_amount

        blocked_column = optional_columns.get("blocked")
        active_card_column = optional_columns.get("active_card")
        blocked_value = client.get(blocked_column) if blocked_column else None
        active_card_value = client.get(active_card_column) if active_card_column else None

        recent_recargas = get_recent_recargas(cursor, limit=5)
        date_offset = describe_date_offset(recent_recargas)

        print(f"Cliente encontrado: si")
        print(f"Cliente ID interno: {client_id}")
        print(
            f"Saldo anterior: {format_argentine_amount(previous_balance)}"
        )
        print(f"Importe: {format_argentine_amount(requested_amount)}")
        print(f"Saldo nuevo: {format_argentine_amount(new_balance)}")
        print(
            f"Estado bloqueado ({blocked_column or 'no disponible'}): {blocked_value}"
        )
        print(
            f"Tarjeta activa ({active_card_column or 'no disponible'}): {active_card_value}"
        )
        print("Diferencia detectada en las fechas:")
        print(f"Ultima Rec_Fecha: {date_offset['latest_recarga_date']}")
        print(f"Fecha actual del servidor: {date_offset['server_now']}")
        print(f"Diferencia aproximada en dias: {date_offset['difference_days']}")
        print(
            "Diferencia aproximada en años: "
            f"{date_offset['difference_years_approx']}"
        )
        print(date_offset["note"])

        print_plan(
            client_id=client_id,
            formatted_new_balance=format_argentine_amount(new_balance),
            formatted_amount=format_argentine_amount(requested_amount),
        )

    except Error as exc:
        print(f"Error MySQL: {exc}")
        raise SystemExit(1)
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1)
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


if __name__ == "__main__":
    main()
