from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from typing import Any

from integrations.woocommerce_client import WooCommerceAPIError, WooCommerceClient
from services.balance_load_service import BalanceLoadService
from services.balance_order_service import BalanceOrderService


class BalancePaymentService:
    def __init__(self) -> None:
        self._woocommerce_client = WooCommerceClient()
        self._balance_order_service = BalanceOrderService()
        self._balance_load_service = BalanceLoadService()

    def check_order(self, order_id: int) -> dict[str, Any]:
        try:
            order = self._woocommerce_client.get_order(order_id)
        except (WooCommerceAPIError, ValueError) as exc:
            return {
                "ok": False,
                "message": str(exc),
            }

        meta = self._meta_to_map(order.get("meta_data"))
        local_order = self._balance_order_service.get_local_order(order_id)
        reference = f"WC-BALANCE-{order_id}"
        local_load = self._get_balance_load(reference)

        validation = self._validate_balance_order(order, meta)
        if not validation["ok"]:
            if local_order:
                self._balance_order_service.update_local_order_status(
                    order_id,
                    status="error",
                    last_error=validation["message"],
                )
            return {
                "ok": False,
                "message": validation["message"],
                "tickera_diagnostics": validation.get("tickera_diagnostics"),
            }

        client_id = int(meta["_bacano_client_id"])
        amount_decimal = str(meta["_bacano_balance_amount"])
        client_lookup = self._find_client_by_id(client_id)
        if not client_lookup.get("ok"):
            return self._build_result(
                order=order,
                client_id=client_id,
                amount_decimal=amount_decimal,
                local_order=local_order,
                local_load=local_load,
                paid=False,
                credited=bool(local_load and local_load.get("status") == "applied"),
                can_credit=False,
                reason=client_lookup.get("message") or "El cliente interno no existe.",
                preview=None,
            )

        paid_eval = self._evaluate_paid_status(order, meta)
        credited = bool(local_load and local_load.get("status") == "applied")
        local_status = self._resolve_local_status(local_order, local_load)
        can_credit = bool(paid_eval["paid"] and not credited)

        self._update_local_state_if_safe(
            order_id=order_id,
            local_order=local_order,
            validation_ok=True,
            paid=paid_eval["paid"],
            cancelled=str(order.get("status") or "") == "cancelled",
            paid_at=str(order.get("date_paid") or "") or None,
        )
        local_order = self._balance_order_service.get_local_order(order_id)
        local_status = self._resolve_local_status(local_order, local_load)

        preview = None
        if not credited:
            preview_result = self._balance_load_service.preview_load(
                client_lookup["dni"],
                amount_decimal,
            )
            if preview_result.get("can_apply"):
                preview = {
                    "previous_balance": preview_result.get("previous_balance"),
                    "amount": preview_result.get("amount"),
                    "new_balance": preview_result.get("new_balance"),
                }
            else:
                can_credit = False
                paid_eval["reason"] = preview_result.get("message") or "No se puede acreditar."

        return self._build_result(
            order=order,
            client_id=client_id,
            amount_decimal=amount_decimal,
            local_order=local_order,
            local_load=local_load,
            paid=paid_eval["paid"],
            credited=credited,
            can_credit=can_credit,
            reason=paid_eval["reason"],
            preview=preview,
            contains_tickera=bool(validation.get("contains_tickera")),
            tickera_diagnostics=validation.get("tickera_diagnostics"),
        )

    def _validate_balance_order(self, order: dict[str, Any], meta: dict[str, str]) -> dict[str, Any]:
        tickera_analysis = self._analyze_tickera_evidence(order, meta)
        if not isinstance(order, dict) or not order.get("id"):
            return {"ok": False, "message": "El pedido no existe.", "tickera_diagnostics": tickera_analysis}

        if meta.get("_bacano_operation_type") != "balance_load":
            return {
                "ok": False,
                "message": "El pedido no es una carga de saldo valida.",
                "tickera_diagnostics": tickera_analysis,
            }

        for key in (
            "_bacano_client_id",
            "_bacano_balance_amount",
            "_bacano_balance_status",
        ):
            if not str(meta.get(key) or "").strip():
                return {
                    "ok": False,
                    "message": f"Falta metadata requerida: {key}",
                    "tickera_diagnostics": tickera_analysis,
                }

        if order.get("line_items"):
            return {
                "ok": False,
                "message": "El pedido de carga tiene line_items reales y es inconsistente.",
                "tickera_diagnostics": tickera_analysis,
            }

        if tickera_analysis["contains_tickera"]:
            return {
                "ok": False,
                "message": "El pedido contiene evidencia concreta de Tickera.",
                "tickera_diagnostics": tickera_analysis,
            }

        total = str(order.get("total") or "").strip()
        expected = str(meta["_bacano_balance_amount"]).strip()
        if not self._same_decimal_amount(total, expected):
            return {
                "ok": False,
                "message": "El total del pedido no coincide con _bacano_balance_amount.",
                "tickera_diagnostics": tickera_analysis,
            }

        return {
            "ok": True,
            "message": None,
            "contains_tickera": False,
            "tickera_diagnostics": tickera_analysis,
        }

    def _evaluate_paid_status(self, order: dict[str, Any], meta: dict[str, str]) -> dict[str, Any]:
        status = str(order.get("status") or "")
        date_paid = order.get("date_paid")
        needs_payment = bool(order.get("needs_payment"))
        payment_method = str(order.get("payment_method") or "")
        transaction_id = str(order.get("transaction_id") or "").strip()

        if status in {"failed", "cancelled", "refunded"}:
            return {"paid": False, "reason": f"Estado WooCommerce no valido: {status}."}
        if status == "pending":
            return {"paid": False, "reason": "El pedido todavia requiere pago."}
        if status == "on-hold" and not date_paid:
            return {"paid": False, "reason": "El pedido esta on-hold sin date_paid."}
        if status not in {"processing", "completed"}:
            return {"paid": False, "reason": f"Estado WooCommerce no habilitado: {status}."}
        if not date_paid:
            return {"paid": False, "reason": "El pedido no tiene date_paid."}
        if needs_payment:
            return {"paid": False, "reason": "WooCommerce indica que el pedido aun necesita pago."}

        mp_reference_present = bool(transaction_id) or "mercado" in payment_method.lower()
        if mp_reference_present:
            return {"paid": True, "reason": "Pago confirmado en WooCommerce."}
        return {
            "paid": True,
            "reason": "Pago confirmado en WooCommerce, sin referencia explicita de Mercado Pago.",
        }

    def _build_result(
        self,
        *,
        order: dict[str, Any],
        client_id: int,
        amount_decimal: str,
        local_order: dict[str, Any] | None,
        local_load: dict[str, Any] | None,
        paid: bool,
        credited: bool,
        can_credit: bool,
        reason: str | None,
        preview: dict[str, Any] | None,
        contains_tickera: bool,
        tickera_diagnostics: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "order_id": int(order.get("id") or 0),
            "woocommerce_status": str(order.get("status") or ""),
            "date_paid": order.get("date_paid"),
            "payment_method": str(order.get("payment_method") or ""),
            "client_id": client_id,
            "amount": amount_decimal,
            "local_status": self._resolve_local_status(local_order, local_load),
            "paid": paid,
            "credited": credited,
            "can_credit": can_credit,
            "reason": reason,
            "preview": preview,
            "reference": f"WC-BALANCE-{int(order.get('id') or 0)}",
            "contains_tickera": contains_tickera,
            "tickera_diagnostics": tickera_diagnostics,
        }

    @staticmethod
    def _meta_to_map(meta_data: Any) -> dict[str, str]:
        result: dict[str, str] = {}
        if not isinstance(meta_data, list):
            return result
        for item in meta_data:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if not key:
                continue
            result[key] = str(item.get("value") or "")
        return result

    @staticmethod
    def _analyze_tickera_evidence(order: dict[str, Any], meta: dict[str, str]) -> dict[str, Any]:
        evidence: list[str] = []
        line_items_summary: list[dict[str, Any]] = []
        for item in order.get("line_items") or []:
            item_meta_keys: list[str] = []
            for meta_item in item.get("meta_data") or []:
                if isinstance(meta_item, dict):
                    key = str(meta_item.get("key") or "").strip()
                    if key:
                        item_meta_keys.append(key)

            product_id = item.get("product_id")
            variation_id = item.get("variation_id")
            name = str(item.get("name") or "").strip()
            line_items_summary.append(
                {
                    "id": item.get("id"),
                    "name": name,
                    "product_id": product_id,
                    "variation_id": variation_id,
                    "meta_keys": item_meta_keys,
                }
            )

            for meta_key in item_meta_keys:
                lowered_key = meta_key.lower()
                if lowered_key.startswith("tc_"):
                    evidence.append(f"line_item_meta:{meta_key}")
                elif lowered_key in {
                    "ticket type",
                    "event",
                    "ticket instance",
                    "ticket_instance",
                    "download_ticket",
                }:
                    evidence.append(f"line_item_meta:{meta_key}")
                elif "ticket_type" in lowered_key or "ticket_instance" in lowered_key:
                    evidence.append(f"line_item_meta:{meta_key}")

        fee_lines_summary = [
            {
                "id": item.get("id"),
                "name": str(item.get("name") or "").strip(),
                "total": item.get("total"),
                "tax_status": item.get("tax_status"),
            }
            for item in (order.get("fee_lines") or [])
            if isinstance(item, dict)
        ]

        order_meta_keys_matching = []
        for key in meta.keys():
            lowered_key = key.lower()
            if lowered_key.startswith("tc_") or "tickera" in lowered_key or "ticket" in lowered_key:
                order_meta_keys_matching.append(key)

        return {
            "contains_tickera": bool(evidence),
            "evidence": evidence,
            "line_items": line_items_summary,
            "fee_lines": fee_lines_summary,
            "order_meta_keys_matching": order_meta_keys_matching,
        }

    @staticmethod
    def _same_decimal_amount(order_total: str, metadata_amount: str) -> bool:
        try:
            return float(order_total) == float(metadata_amount)
        except Exception:
            return False

    def _find_client_by_id(self, client_id: int) -> dict[str, Any]:
        connection = None
        cursor = None
        try:
            connection = self._balance_load_service._connect_mysql(read_only=True)
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT `Cli_Indice`, `Cli_DNI`, `Cli_Razon`
                FROM `clientes`
                WHERE `Cli_Indice` = %s
                """,
                (client_id,),
            )
            row = cursor.fetchone()
            if not row:
                return {
                    "ok": False,
                    "message": "El cliente interno ya no existe en MySQL.",
                }
            return {
                "ok": True,
                "client_id": int(row["Cli_Indice"]),
                "dni": str(row.get("Cli_DNI") or "").strip(),
                "name": str(row.get("Cli_Razon") or "").strip(),
            }
        except Exception as exc:
            return {
                "ok": False,
                "message": str(exc) or "No se pudo validar el cliente interno.",
            }
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None and connection.is_connected():
                connection.close()

    def _get_balance_load(self, reference: str) -> dict[str, Any] | None:
        with self._balance_order_service._connect_sqlite() as conn:
            row = conn.execute(
                "SELECT * FROM balance_loads WHERE reference = ?",
                (reference,),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _resolve_local_status(
        local_order: dict[str, Any] | None,
        local_load: dict[str, Any] | None,
    ) -> str:
        if local_load and local_load.get("status") == "applied":
            return "credited"
        if local_load and local_load.get("status"):
            return str(local_load["status"])
        if local_order and local_order.get("status"):
            return str(local_order["status"])
        return "not_found"

    def _update_local_state_if_safe(
        self,
        *,
        order_id: int,
        local_order: dict[str, Any] | None,
        validation_ok: bool,
        paid: bool,
        cancelled: bool,
        paid_at: str | None,
    ) -> None:
        if not local_order:
            return
        if not validation_ok:
            self._balance_order_service.update_local_order_status(
                order_id,
                status="error",
                last_error="metadata_invalida",
            )
            return
        if cancelled:
            self._balance_order_service.update_local_order_status(
                order_id,
                status="cancelled",
                last_error=None,
            )
            return
        if paid:
            self._balance_order_service.update_local_order_status(
                order_id,
                status="paid",
                paid_at=paid_at,
                last_error=None,
            )
            return
        self._balance_order_service.update_local_order_status(
            order_id,
            status="awaiting_payment",
            last_error=None,
        )
