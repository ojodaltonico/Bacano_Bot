from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from integrations.woocommerce_client import WooCommerceAPIError, WooCommerceClient
from services.balance_load_service import BalanceLoadService
from services.delivery_state_service import DB_PATH
from utils.phone_utils import mask_phone, normalize_argentine_phone


class BalanceOrderError(Exception):
    pass


class BalanceOrderService:
    def __init__(self, sqlite_db_path: Path | None = None) -> None:
        self._woocommerce_client = WooCommerceClient()
        self._balance_load_service = BalanceLoadService(sqlite_db_path=sqlite_db_path)
        self._sqlite_db_path = Path(sqlite_db_path) if sqlite_db_path else DB_PATH
        self._sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()
        self._created_request_keys: set[tuple[str, str, str, str]] = set()

    def preview_order(
        self,
        dni: str,
        amount: str,
        phone: str,
        email: str | None = None,
    ) -> dict[str, Any]:
        normalized_email = self._validate_optional_email(email)
        normalized_phone = self._validate_phone(phone)

        preview = self._balance_load_service.preview_load(dni, amount)
        if not preview.get("can_apply"):
            return {
                "ok": False,
                "message": preview.get("message"),
                "reason": preview.get("reason"),
                "client_ids": preview.get("client_ids", []),
            }

        name = str(preview.get("name") or "").strip()
        first_name, last_name = self._split_name(name)
        amount_decimal = self._parse_formatted_amount(str(preview["amount"]))

        return {
            "ok": True,
            "client_id": int(preview["client_id"]),
            "name": name,
            "dni_masked": self._mask_dni(str(dni)),
            "amount_decimal": f"{amount_decimal:.2f}",
            "amount_display": str(preview["amount"]),
            "email": normalized_email,
            "phone_masked": mask_phone(normalized_phone),
            "phone_normalized": normalized_phone,
            "first_name": first_name,
            "last_name": last_name,
            "blocked": preview.get("blocked"),
            "active_card": preview.get("active_card"),
        }

    def create_order(
        self,
        dni: str,
        amount: str,
        phone: str,
        confirmed_client_id: int,
        email: str | None = None,
    ) -> dict[str, Any]:
        preview = self.preview_order(dni, amount, phone, email=email)
        if not preview.get("ok"):
            return {
                "ok": False,
                "message": preview.get("message"),
                "reason": preview.get("reason"),
            }

        client_id = int(preview["client_id"])
        if int(confirmed_client_id) != client_id:
            return {
                "ok": False,
                "reason": "client_confirmation_mismatch",
                "message": "El ID confirmado no coincide con el cliente encontrado.",
            }

        request_key = (
            self._normalize_dni(dni),
            str(preview["amount_decimal"]),
            str(preview.get("email") or "").strip().lower(),
            str(preview["phone_normalized"]),
        )
        if request_key in self._created_request_keys:
            return {
                "ok": False,
                "reason": "duplicate_request_in_process",
                "message": "La misma ejecucion ya intento crear este pedido en este proceso.",
            }

        billing = {
            "first_name": preview["first_name"],
            "last_name": preview["last_name"],
            "phone": preview["phone_normalized"],
            "country": "AR",
        }
        if preview.get("email"):
            billing["email"] = preview["email"]

        payload = {
            "status": "pending",
            "set_paid": False,
            "payment_method": "",
            "payment_method_title": "",
            "billing": billing,
            "fee_lines": [
                {
                    "name": "Carga de saldo Bacano",
                    "total": str(preview["amount_decimal"]),
                    "tax_status": "none",
                }
            ],
            "meta_data": [
                {"key": "_bacano_operation_type", "value": "balance_load"},
                {"key": "_bacano_client_id", "value": str(client_id)},
                {"key": "_bacano_dni_last4", "value": self._last4(self._normalize_dni(dni))},
                {"key": "_bacano_balance_amount", "value": str(preview["amount_decimal"])},
                {"key": "_bacano_source", "value": "whatsapp_bot"},
                {"key": "_bacano_balance_status", "value": "awaiting_payment"},
            ],
            "customer_note": "",
        }

        note_text = (
            "Carga de saldo solicitada desde Bacano Bot.\n"
            f"Cliente interno: {client_id}.\n"
            "Pendiente de acreditacion luego de confirmar el pago."
        )

        try:
            created_order = self._woocommerce_client.create_order(payload)
            order_id = int(created_order.get("id") or 0)
            if not order_id:
                raise BalanceOrderError("WooCommerce no devolvio un ID de pedido valido.")

            self._woocommerce_client.create_order_note(
                order_id=order_id,
                note=note_text,
                customer_note=False,
            )
            payment_url = self._resolve_payment_url(created_order)
            self._insert_balance_order(
                woocommerce_order_id=order_id,
                client_id=client_id,
                dni_last4=self._last4(self._normalize_dni(dni)),
                amount=str(preview["amount_decimal"]),
                email=preview.get("email"),
                phone_masked=str(preview["phone_masked"]),
                status="awaiting_payment",
                payment_url=payment_url,
                created_at=self._now_iso(),
                paid_at=None,
                credited_at=None,
                last_error=None,
            )
            self._created_request_keys.add(request_key)
            return {
                "ok": True,
                "order_id": order_id,
                "status": str(created_order.get("status") or "pending"),
                "amount": str(preview["amount_display"]),
                "client_name": str(preview["name"]),
                "payment_url": payment_url,
            }
        except (WooCommerceAPIError, BalanceOrderError, sqlite3.Error) as exc:
            return {
                "ok": False,
                "reason": "create_order_failed",
                "message": str(exc),
            }

    def get_local_order(self, order_id: int) -> dict[str, Any] | None:
        with self._connect_sqlite() as conn:
            row = conn.execute(
                "SELECT * FROM balance_orders WHERE woocommerce_order_id = ?",
                (order_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_local_order_status(
        self,
        order_id: int,
        *,
        status: str,
        paid_at: str | None = None,
        credited_at: str | None = None,
        last_error: str | None = None,
    ) -> None:
        with self._connect_sqlite() as conn:
            conn.execute(
                """
                UPDATE balance_orders
                SET status = ?,
                    paid_at = COALESCE(?, paid_at),
                    credited_at = COALESCE(?, credited_at),
                    last_error = ?
                WHERE woocommerce_order_id = ?
                """,
                (status, paid_at, credited_at, last_error, order_id),
            )
            conn.commit()

    def _resolve_payment_url(self, created_order: dict[str, Any]) -> str:
        payment_url = str(created_order.get("payment_url") or "").strip()
        if payment_url:
            self._validate_payment_url(payment_url)
            return payment_url

        order_id = int(created_order.get("id") or 0)
        order_key = str(created_order.get("order_key") or "").strip()
        if not order_id or not order_key:
            raise BalanceOrderError("No se pudo construir la URL de pago del pedido.")

        fallback_url = (
            f"{self._woocommerce_client.base_url}/checkout/order-pay/{order_id}/"
            f"?pay_for_order=true&key={order_key}"
        )
        self._validate_payment_url(fallback_url)
        return fallback_url

    @staticmethod
    def _validate_payment_url(url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host != "bacanoclub.com.ar":
            raise BalanceOrderError("La URL de pago no pertenece a bacanoclub.com.ar.")

    @staticmethod
    def _split_name(full_name: str) -> tuple[str, str]:
        parts = [part for part in str(full_name or "").split() if part]
        if not parts:
            return "", ""
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], " ".join(parts[1:])

    @staticmethod
    def _validate_optional_email(email: str | None) -> str | None:
        normalized = str(email or "").strip()
        if not normalized:
            return None
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise BalanceOrderError("El correo es invalido.")
        return normalized

    @staticmethod
    def _validate_phone(phone: str) -> str:
        normalized = normalize_argentine_phone(phone)
        if not normalized:
            raise BalanceOrderError("El telefono no es normalizable.")
        return normalized

    @staticmethod
    def _normalize_dni(dni: str) -> str:
        normalized = "".join(char for char in str(dni or "") if char.isdigit())
        if not normalized:
            raise BalanceOrderError("El DNI debe ser numerico.")
        return normalized

    @staticmethod
    def _mask_dni(dni: str) -> str:
        digits = "".join(char for char in str(dni or "") if char.isdigit())
        if len(digits) <= 2:
            return "*" * len(digits)
        if len(digits) <= 4:
            return "*" * (len(digits) - 2) + digits[-2:]
        return "*" * (len(digits) - 4) + digits[-4:]

    @staticmethod
    def _last4(value: str) -> str:
        return value[-4:] if len(value) >= 4 else value

    @staticmethod
    def _parse_formatted_amount(value: str) -> Decimal:
        raw = str(value or "").strip()
        if not raw:
            raise BalanceOrderError("El importe es invalido.")
        sanitized = raw.replace(".", "").replace(",", ".")
        try:
            return Decimal(sanitized).quantize(Decimal("0.01"))
        except Exception as exc:
            raise BalanceOrderError("El importe es invalido.") from exc

    def _init_sqlite(self) -> None:
        with self._connect_sqlite() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS balance_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    woocommerce_order_id INTEGER UNIQUE,
                    client_id INTEGER NOT NULL,
                    dni_last4 TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    email TEXT,
                    phone_masked TEXT,
                    status TEXT NOT NULL,
                    payment_url TEXT,
                    created_at TEXT NOT NULL,
                    paid_at TEXT,
                    credited_at TEXT,
                    last_error TEXT
                )
                """
            )
            conn.commit()

    def _insert_balance_order(
        self,
        *,
        woocommerce_order_id: int,
        client_id: int,
        dni_last4: str,
        amount: str,
        email: str | None,
        phone_masked: str,
        status: str,
        payment_url: str,
        created_at: str,
        paid_at: str | None,
        credited_at: str | None,
        last_error: str | None,
    ) -> None:
        with self._connect_sqlite() as conn:
            conn.execute(
                """
                INSERT INTO balance_orders (
                    woocommerce_order_id,
                    client_id,
                    dni_last4,
                    amount,
                    email,
                    phone_masked,
                    status,
                    payment_url,
                    created_at,
                    paid_at,
                    credited_at,
                    last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    woocommerce_order_id,
                    client_id,
                    dni_last4,
                    amount,
                    email,
                    phone_masked,
                    status,
                    payment_url,
                    created_at,
                    paid_at,
                    credited_at,
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
