from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import sqlite3
from pathlib import Path
from typing import Any

import mysql.connector
from mysql.connector import Error

from config_manager import load_config
from services.delivery_state_service import DB_PATH


MIN_AMOUNT = Decimal("1000")
MAX_AMOUNT = Decimal("500000")
TWOPLACES = Decimal("0.01")


class BalanceLoadError(Exception):
    pass


@dataclass
class ClientRecord:
    client_id: int
    name: str
    dni: str
    previous_balance: Decimal
    blocked: Any
    active_card: Any


class BalanceLoadService:
    def __init__(self, sqlite_db_path: Path | None = None) -> None:
        self._sqlite_db_path = Path(sqlite_db_path) if sqlite_db_path else DB_PATH
        self._sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()

    def find_client_by_dni(self, dni: str) -> dict[str, Any]:
        try:
            normalized_dni = self._normalize_dni(dni)
        except BalanceLoadError as exc:
            return {
                "ok": False,
                "reason": "invalid_dni",
                "message": str(exc),
                "dni": "",
            }
        connection = None
        cursor = None
        try:
            connection = self._connect_mysql(read_only=True)
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    `Cli_Indice`,
                    `Cli_Razon`,
                    `Cli_DNI`,
                    `Cli_Adelantos`,
                    `Cli_Bloqueado`,
                    `Cli_TJ_Activa`
                FROM `clientes`
                WHERE `Cli_DNI` = %s
                """,
                (normalized_dni,),
            )
            rows = list(cursor.fetchall())

            if not rows:
                return {
                    "ok": False,
                    "reason": "client_not_found",
                    "message": "No existe un cliente con ese DNI.",
                    "dni": normalized_dni,
                }

            if len(rows) > 1:
                return {
                    "ok": False,
                    "reason": "multiple_clients",
                    "message": "Existen varios clientes con el mismo DNI.",
                    "dni": normalized_dni,
                    "client_ids": [int(row["Cli_Indice"]) for row in rows],
                }

            client = self._row_to_client(rows[0])
            return {
                "ok": True,
                "client": self._client_to_dict(client),
            }
        except Error as exc:
            return {
                "ok": False,
                "reason": "mysql_error",
                "message": str(exc),
                "dni": normalized_dni,
            }
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None and connection.is_connected():
                connection.close()

    def preview_load(self, dni: str, amount: str | int | float | Decimal) -> dict[str, Any]:
        client_result = self.find_client_by_dni(dni)
        if not client_result.get("ok"):
            return {
                "ok": False,
                "can_apply": False,
                "reason": client_result.get("reason"),
                "message": client_result.get("message"),
                "client_ids": client_result.get("client_ids", []),
            }

        try:
            requested_amount = self._validate_requested_amount(amount)
        except BalanceLoadError as exc:
            return {
                "ok": False,
                "can_apply": False,
                "reason": "invalid_amount",
                "message": str(exc),
            }

        client = client_result["client"]
        blocked = self._is_explicitly_blocked(client.get("blocked"))
        previous_balance = self._parse_argentine_amount(client.get("previous_balance"))
        new_balance = previous_balance + requested_amount

        can_apply = True
        reason = None
        if not client.get("client_id"):
            can_apply = False
            reason = "missing_client_id"
        elif blocked:
            can_apply = False
            reason = "client_blocked"

        return {
            "ok": can_apply,
            "can_apply": can_apply,
            "reason": reason,
            "message": self._preview_message(reason),
            "client": client,
            "client_id": client["client_id"],
            "name": client["name"],
            "previous_balance": self._format_argentine_amount(previous_balance),
            "amount": self._format_argentine_amount(requested_amount),
            "new_balance": self._format_argentine_amount(new_balance),
            "blocked": client.get("blocked"),
            "active_card": client.get("active_card"),
        }

    def apply_load(
        self,
        dni: str,
        amount: str | int | float | Decimal,
        reference: str,
        confirmed_client_id: int,
    ) -> dict[str, Any]:
        reference = str(reference or "").strip()
        if not reference:
            return {
                "ok": False,
                "reason": "missing_reference",
                "message": "La referencia no puede estar vacia.",
            }

        preview = self.preview_load(dni, amount)
        if not preview.get("can_apply"):
            return {
                "ok": False,
                "reason": preview.get("reason"),
                "message": preview.get("message"),
            }

        client_id = int(preview["client_id"])
        if int(confirmed_client_id) != client_id:
            return {
                "ok": False,
                "reason": "client_confirmation_mismatch",
                "message": "El ID confirmado no coincide con el cliente encontrado.",
            }

        reference_state = self._get_balance_load(reference)
        if reference_state and reference_state.get("status") == "applied":
            return {
                "ok": False,
                "reason": "reference_already_applied",
                "message": "La referencia ya fue acreditada.",
            }
        if reference_state and reference_state.get("status") == "processing":
            return {
                "ok": False,
                "reason": "reference_processing",
                "message": "La referencia ya esta en procesamiento.",
            }

        requested_amount = self._validate_requested_amount(amount)
        mysql_connection = None
        mysql_cursor = None
        formatted_amount = self._format_argentine_amount(requested_amount)
        now_iso = self._now_iso()
        self._upsert_balance_load(
            reference=reference,
            client_id=client_id,
            amount=formatted_amount,
            status="processing",
            previous_balance=preview["previous_balance"],
            new_balance=None,
            recarga_id=None,
            historial_id=None,
            created_at=reference_state["created_at"] if reference_state else now_iso,
            applied_at=None,
            last_error=None,
        )

        try:
            mysql_connection = self._connect_mysql(read_only=False)
            mysql_connection.start_transaction()
            mysql_cursor = mysql_connection.cursor(dictionary=True)

            mysql_cursor.execute("SELECT NOW() AS server_now")
            server_now_row = mysql_cursor.fetchone() or {}
            server_now = server_now_row.get("server_now")
            if isinstance(server_now, datetime):
                server_now_str = server_now.strftime("%Y-%m-%d %H:%M:%S")
            else:
                server_now_str = str(server_now)

            mysql_cursor.execute(
                """
                SELECT `Cli_Indice`, `Cli_Adelantos`
                FROM `clientes`
                WHERE `Cli_Indice` = %s
                FOR UPDATE
                """,
                (client_id,),
            )
            locked_row = mysql_cursor.fetchone()
            if not locked_row:
                raise BalanceLoadError("No se encontro el cliente dentro de la transaccion.")

            previous_balance = self._parse_argentine_amount(locked_row.get("Cli_Adelantos"))
            new_balance = previous_balance + requested_amount
            formatted_new_balance = self._format_argentine_amount(new_balance)

            mysql_cursor.execute(
                """
                UPDATE `clientes`
                SET `Cli_Adelantos` = %s
                WHERE `Cli_Indice` = %s
                """,
                (formatted_new_balance, client_id),
            )

            mysql_cursor.execute(
                """
                INSERT INTO `recargas` (
                    `Rec_Fecha`,
                    `Rec_IdCli`,
                    `Rec_Numcaja`,
                    `Rec_TipoPago`,
                    `Rec_Importe`
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    server_now_str,
                    client_id,
                    "BOT",
                    "TARJETA",
                    formatted_amount,
                ),
            )
            recarga_id = int(mysql_cursor.lastrowid)

            mysql_cursor.execute(
                """
                INSERT INTO `historial` (
                    `Hist_Fecha`,
                    `Hist_Id`,
                    `Hist_Caja`,
                    `Hist_ID_ART`,
                    `Hist_Detalle`,
                    `Hist_Cant`,
                    `Hist_Unitario`,
                    `Hist_Total`
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    server_now_str,
                    client_id,
                    "BOT",
                    "RECARGA",
                    "RECARGA TARJETA BOT",
                    "-",
                    "-",
                    formatted_amount,
                ),
            )
            historial_id = int(mysql_cursor.lastrowid)
            mysql_connection.commit()

            self._upsert_balance_load(
                reference=reference,
                client_id=client_id,
                amount=formatted_amount,
                status="applied",
                previous_balance=self._format_argentine_amount(previous_balance),
                new_balance=formatted_new_balance,
                recarga_id=recarga_id,
                historial_id=historial_id,
                created_at=reference_state["created_at"] if reference_state else now_iso,
                applied_at=self._now_iso(),
                last_error=None,
            )

            return {
                "ok": True,
                "client_id": client_id,
                "name": preview["name"],
                "previous_balance": self._format_argentine_amount(previous_balance),
                "amount": formatted_amount,
                "new_balance": formatted_new_balance,
                "recarga_id": recarga_id,
                "historial_id": historial_id,
                "date_used": server_now_str,
                "reference": reference,
            }
        except (Error, BalanceLoadError) as exc:
            if mysql_connection is not None:
                try:
                    mysql_connection.rollback()
                except Exception:
                    pass
            self._upsert_balance_load(
                reference=reference,
                client_id=client_id,
                amount=formatted_amount,
                status="error",
                previous_balance=preview["previous_balance"],
                new_balance=None,
                recarga_id=None,
                historial_id=None,
                created_at=reference_state["created_at"] if reference_state else now_iso,
                applied_at=None,
                last_error=str(exc),
            )
            return {
                "ok": False,
                "reason": "apply_failed",
                "message": str(exc),
            }
        finally:
            if mysql_cursor is not None:
                mysql_cursor.close()
            if mysql_connection is not None and mysql_connection.is_connected():
                mysql_connection.close()

    def verify_applied_load(self, client_id: int, recarga_id: int, historial_id: int) -> dict[str, Any]:
        connection = None
        cursor = None
        try:
            connection = self._connect_mysql(read_only=True)
            cursor = connection.cursor(dictionary=True)
            client_row = self._fetch_client_by_id(cursor, client_id)
            recarga_row = self._fetch_recarga_by_id(cursor, recarga_id)
            historial_row = self._fetch_historial_by_id(cursor, historial_id)
            return {
                "ok": True,
                "client_balance": self._format_argentine_amount(
                    self._parse_argentine_amount(client_row.get("Cli_Adelantos"))
                )
                if client_row
                else None,
                "recarga_row": recarga_row,
                "historial_row": historial_row,
            }
        except Error as exc:
            return {
                "ok": False,
                "message": str(exc),
            }
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None and connection.is_connected():
                connection.close()

    def _connect_mysql(self, read_only: bool) -> mysql.connector.MySQLConnection:
        config = load_config()
        db_config = config.get("database", {})
        required = ("host", "user", "password", "database")
        missing = [key for key in required if not str(db_config.get(key) or "").strip()]
        if missing:
            raise BalanceLoadError(
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
            autocommit=read_only,
        )

    def _fetch_client_by_id(self, cursor, client_id: int) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT `Cli_Indice`, `Cli_Adelantos`
            FROM `clientes`
            WHERE `Cli_Indice` = %s
            """,
            (client_id,),
        )
        return cursor.fetchone()

    def _fetch_recarga_by_id(self, cursor, recarga_id: int) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT
                `Rec_indice`,
                `Rec_Fecha`,
                `Rec_IdCli`,
                `Rec_Numcaja`,
                `Rec_TipoPago`,
                `Rec_Importe`
            FROM `recargas`
            WHERE `Rec_indice` = %s
            """,
            (recarga_id,),
        )
        return cursor.fetchone()

    def _fetch_historial_by_id(self, cursor, historial_id: int) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT
                `Hist_Indice`,
                `Hist_Fecha`,
                `Hist_Id`,
                `Hist_Caja`,
                `Hist_ID_ART`,
                `Hist_Detalle`,
                `Hist_Cant`,
                `Hist_Unitario`,
                `Hist_Total`
            FROM `historial`
            WHERE `Hist_Indice` = %s
            """,
            (historial_id,),
        )
        return cursor.fetchone()

    def _row_to_client(self, row: dict[str, Any]) -> ClientRecord:
        return ClientRecord(
            client_id=int(row["Cli_Indice"]),
            name=str(row.get("Cli_Razon") or "").strip(),
            dni=str(row.get("Cli_DNI") or "").strip(),
            previous_balance=self._parse_argentine_amount(row.get("Cli_Adelantos")),
            blocked=row.get("Cli_Bloqueado"),
            active_card=row.get("Cli_TJ_Activa"),
        )

    @staticmethod
    def _client_to_dict(client: ClientRecord) -> dict[str, Any]:
        return {
            "client_id": client.client_id,
            "name": client.name,
            "dni": client.dni,
            "previous_balance": BalanceLoadService._format_argentine_amount(client.previous_balance),
            "blocked": client.blocked,
            "active_card": client.active_card,
        }

    @staticmethod
    def _normalize_dni(dni: str) -> str:
        normalized = "".join(char for char in str(dni or "") if char.isdigit())
        if not normalized:
            raise BalanceLoadError("El DNI debe ser numerico.")
        return normalized

    @staticmethod
    def _parse_argentine_amount(value: Any) -> Decimal:
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
            raise BalanceLoadError(f"Importe invalido almacenado: {value}") from exc

        return amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    @staticmethod
    def _validate_requested_amount(value: str | int | float | Decimal) -> Decimal:
        raw = str(value).strip()
        if not raw:
            raise BalanceLoadError("El importe es obligatorio.")

        normalized_input = raw.replace(" ", "")
        if "," in normalized_input:
            decimal_part = normalized_input.split(",")[-1]
            if len(decimal_part) > 2:
                raise BalanceLoadError("El importe no puede tener mas de dos decimales.")
        elif normalized_input.count(".") == 1:
            integer_part, decimal_part = normalized_input.split(".")
            if decimal_part and len(decimal_part) not in {3} and len(decimal_part) > 2:
                raise BalanceLoadError("El importe no puede tener mas de dos decimales.")
            if not re.fullmatch(r"\d+", integer_part):
                raise BalanceLoadError("El importe no es numerico.")

        try:
            amount = BalanceLoadService._parse_argentine_amount(raw)
        except BalanceLoadError:
            raise

        if amount <= 0:
            raise BalanceLoadError("El importe debe ser positivo.")
        if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
            raise BalanceLoadError("El importe debe estar entre $1.000 y $500.000.")
        return amount

    @staticmethod
    def _format_argentine_amount(amount: Decimal) -> str:
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

    @staticmethod
    def _is_explicitly_blocked(value: Any) -> bool:
        normalized = str(value or "").strip().lower()
        return normalized in {"1", "si", "sí", "s", "true", "bloqueado", "yes", "y"}

    @staticmethod
    def _preview_message(reason: str | None) -> str | None:
        mapping = {
            None: None,
            "missing_client_id": "Falta el ID interno del cliente.",
            "client_blocked": "El cliente esta marcado como bloqueado.",
        }
        return mapping.get(reason, "No se puede cargar el saldo.")

    def _init_sqlite(self) -> None:
        with self._connect_sqlite() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS balance_loads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reference TEXT NOT NULL UNIQUE,
                    client_id INTEGER NOT NULL,
                    amount TEXT NOT NULL,
                    status TEXT NOT NULL,
                    previous_balance TEXT,
                    new_balance TEXT,
                    recarga_id INTEGER,
                    historial_id INTEGER,
                    created_at TEXT NOT NULL,
                    applied_at TEXT,
                    last_error TEXT
                )
                """
            )
            conn.commit()

    def _get_balance_load(self, reference: str) -> dict[str, Any] | None:
        with self._connect_sqlite() as conn:
            row = conn.execute(
                "SELECT * FROM balance_loads WHERE reference = ?",
                (reference,),
            ).fetchone()
        return dict(row) if row else None

    def _upsert_balance_load(
        self,
        *,
        reference: str,
        client_id: int,
        amount: str,
        status: str,
        previous_balance: str | None,
        new_balance: str | None,
        recarga_id: int | None,
        historial_id: int | None,
        created_at: str,
        applied_at: str | None,
        last_error: str | None,
    ) -> None:
        with self._connect_sqlite() as conn:
            conn.execute(
                """
                INSERT INTO balance_loads (
                    reference,
                    client_id,
                    amount,
                    status,
                    previous_balance,
                    new_balance,
                    recarga_id,
                    historial_id,
                    created_at,
                    applied_at,
                    last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(reference) DO UPDATE SET
                    client_id = excluded.client_id,
                    amount = excluded.amount,
                    status = excluded.status,
                    previous_balance = excluded.previous_balance,
                    new_balance = excluded.new_balance,
                    recarga_id = excluded.recarga_id,
                    historial_id = excluded.historial_id,
                    applied_at = excluded.applied_at,
                    last_error = excluded.last_error
                """,
                (
                    reference,
                    client_id,
                    amount,
                    status,
                    previous_balance,
                    new_balance,
                    recarga_id,
                    historial_id,
                    created_at,
                    applied_at,
                    last_error,
                ),
            )
            conn.commit()

    def _connect_sqlite(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._sqlite_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
