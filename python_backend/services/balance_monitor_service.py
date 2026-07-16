from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from integrations.woocommerce_client import WooCommerceAPIError, WooCommerceClient
from services.balance_credit_service import BalanceCreditService
from services.balance_order_service import BalanceOrderService


class BalanceMonitorService:
    def __init__(
        self,
        woocommerce_client: WooCommerceClient | None = None,
        credit_service: BalanceCreditService | None = None,
        order_service: BalanceOrderService | None = None,
    ) -> None:
        self._woocommerce_client = woocommerce_client or WooCommerceClient()
        self._credit_service = credit_service or BalanceCreditService()
        self._order_service = order_service or BalanceOrderService()

    def scan_recent_orders(
        self,
        *,
        live: bool = False,
        limit: int = 50,
        after_order_id: int | None = None,
        after_date: str | None = None,
    ) -> dict[str, Any]:
        if limit <= 0 or limit > 100:
            raise ValueError("limit debe estar entre 1 y 100.")

        orders = self._fetch_order_pages(
            page_size=limit,
            after_order_id=after_order_id,
            after_date=after_date,
        )

        results = []
        unique_orders = {
            self._safe_int(order.get("id")): order
            for order in orders
            if self._safe_int(order.get("id")) is not None
        }
        for order in sorted(unique_orders.values(), key=lambda item: self._safe_int(item.get("id")) or 0):
            try:
                result = self._process_order(
                    order,
                    live=live,
                    after_order_id=after_order_id,
                )
            except Exception as exc:
                order_id = self._safe_int(order.get("id")) or 0
                message = self._safe_message(str(exc) or "Error inesperado procesando el pedido.")
                self._record_local_error(order_id, message)
                result = self._error_result(
                    order_id,
                    message,
                    order=order,
                    meta=self._meta_to_map(order.get("meta_data")),
                )
            if result is not None:
                results.append(result)

        return {
            "mode": "live" if live else "dry-run",
            "filters": {
                "limit": limit,
                "after_order_id": after_order_id,
                "after_date": after_date,
            },
            "summary": self._build_summary(results),
            "results": results,
        }

    def _fetch_order_pages(
        self,
        *,
        page_size: int,
        after_order_id: int | None,
        after_date: str | None,
    ) -> list[dict[str, Any]]:
        orders: list[dict[str, Any]] = []
        page = 1
        while True:
            page_orders = self._woocommerce_client.get_orders(
                per_page=page_size,
                page=page,
                after=after_date,
            )
            if not isinstance(page_orders, list):
                raise WooCommerceAPIError("WooCommerce no devolvio una lista de pedidos.")
            if not page_orders:
                break

            orders.extend(item for item in page_orders if isinstance(item, dict))
            if len(page_orders) < page_size:
                break
            if after_order_id is None and after_date is None:
                break

            valid_ids = [self._safe_int(item.get("id")) for item in page_orders if isinstance(item, dict)]
            if after_order_id is not None and valid_ids and all(
                order_id is not None and order_id <= after_order_id for order_id in valid_ids
            ):
                break
            page += 1
        return orders

    def _process_order(
        self,
        order: dict[str, Any],
        *,
        live: bool,
        after_order_id: int | None,
    ) -> dict[str, Any] | None:
        order_id = self._safe_int(order.get("id"))
        if not order_id:
            return self._error_result(0, "WooCommerce devolvio un pedido sin ID valido.")
        if after_order_id is not None and order_id <= after_order_id:
            return None

        meta = self._meta_to_map(order.get("meta_data"))
        if meta.get("_bacano_operation_type") != "balance_load":
            return None

        payment_method = str(order.get("payment_method") or "")
        if payment_method != "woo-mercado-pago-custom":
            return {
                "order_id": order_id,
                "status": "ignored",
                "reason": f"Metodo no habilitado: {payment_method or '-'}.",
                "admin_alert_required": False,
            }

        preview = self._credit_service.preview_credit(order_id)
        if not preview.get("ok"):
            check = preview.get("check") or preview
            reason = str(preview.get("reason") or "")
            if reason == "already_credited" or check.get("credited"):
                return {
                    "order_id": order_id,
                    "status": "ignored",
                    "reason": "El pedido ya estaba acreditado.",
                    "reference": check.get("reference") or f"WC-BALANCE-{order_id}",
                    "admin_alert_required": False,
                }

            if reason == "payment_not_confirmed" and not check.get("admin_alert_required"):
                return {
                    "order_id": order_id,
                    "status": "waiting",
                    "reason": preview.get("message") or check.get("reason"),
                    "admin_alert_required": False,
                }

            message = str(preview.get("message") or check.get("message") or "Pedido inconsistente.")
            self._record_local_error(order_id, message)
            return self._error_result(
                order_id,
                message,
                order=order,
                check=check,
                meta=meta,
                alert_message=check.get("admin_alert_message"),
            )

        if not live:
            return {
                "order_id": order_id,
                "status": "would_credit",
                "reason": "Pago valido; se acreditaria solo en modo live.",
                "client_id": preview.get("client_id"),
                "client_name": preview.get("client_name"),
                "amount": preview.get("amount"),
                "reference": preview.get("reference"),
                "preview": preview.get("preview"),
                "admin_alert_required": False,
            }

        applied = self._credit_service.apply_credit(order_id, int(preview["client_id"]))
        if not applied.get("ok"):
            message = str(applied.get("message") or "No se pudo acreditar el pedido.")
            if applied.get("reason") == "already_credited":
                return {
                    "order_id": order_id,
                    "status": "ignored",
                    "reason": "El pedido fue acreditado por otro proceso.",
                    "reference": f"WC-BALANCE-{order_id}",
                    "admin_alert_required": False,
                }
            self._record_local_error(order_id, message)
            return self._error_result(
                order_id,
                message,
                order=order,
                check=applied.get("check"),
                meta=meta,
            )

        return {
            "order_id": order_id,
            "status": "credited",
            "reason": "Saldo acreditado correctamente.",
            "client_id": applied.get("client_id"),
            "amount": applied.get("amount"),
            "reference": applied.get("reference"),
            "recarga_id": applied.get("recarga_id"),
            "historial_id": applied.get("historial_id"),
            "verification": applied.get("verification"),
            "woocommerce_note_error": applied.get("woocommerce_note_error"),
            "admin_alert_required": bool(applied.get("woocommerce_note_error")),
        }

    def _record_local_error(self, order_id: int, message: str) -> None:
        try:
            if self._order_service.get_local_order(order_id):
                self._order_service.update_local_order_status(
                    order_id,
                    status="error",
                    last_error=message,
                )
        except Exception:
            # El resultado administrativo debe seguir disponible aunque falle SQLite.
            return

    @staticmethod
    def _error_result(
        order_id: int,
        message: str,
        *,
        order: dict[str, Any] | None = None,
        check: dict[str, Any] | None = None,
        meta: dict[str, str] | None = None,
        alert_message: str | None = None,
    ) -> dict[str, Any]:
        order = order or {}
        check = check or {}
        meta = meta or {}
        safe_message = BalanceMonitorService._safe_message(message)
        woocommerce_status = str(check.get("woocommerce_status") or order.get("status") or "")
        payment_method = str(check.get("payment_method") or order.get("payment_method") or "")
        client_id = check.get("client_id") or BalanceMonitorService._safe_int(
            meta.get("_bacano_client_id")
        )
        amount = check.get("amount") or meta.get("_bacano_balance_amount") or order.get("total")
        return {
            "order_id": order_id,
            "status": "error",
            "woocommerce_status": woocommerce_status,
            "payment_method": payment_method,
            "client_id": client_id,
            "amount": amount,
            "reason": safe_message,
            "admin_alert_required": True,
            "admin_alert_message": BalanceMonitorService._safe_message(alert_message) if alert_message else (
                "ALERTA BACANO BOT - MONITOR DE SALDO\n"
                f"Order ID: {order_id}\n"
                f"Estado WooCommerce: {woocommerce_status or '-'}\n"
                f"Metodo de pago: {payment_method or '-'}\n"
                f"Cliente interno: {client_id if client_id is not None else '-'}\n"
                f"Importe: {amount or '-'}\n"
                f"Motivo: {safe_message}"
            ),
        }

    @staticmethod
    def _build_summary(results: list[dict[str, Any]]) -> dict[str, int]:
        summary = {
            "analyzed": len(results),
            "would_credit": 0,
            "credited": 0,
            "ignored": 0,
            "waiting": 0,
            "errors": 0,
        }
        for item in results:
            status = str(item.get("status") or "")
            key = "errors" if status == "error" else status
            if key in summary:
                summary[key] += 1
        return summary

    @staticmethod
    def _meta_to_map(meta_data: Any) -> dict[str, str]:
        result: dict[str, str] = {}
        if not isinstance(meta_data, list):
            return result
        for item in meta_data:
            if isinstance(item, dict) and str(item.get("key") or "").strip():
                result[str(item["key"]).strip()] = str(item.get("value") or "")
        return result

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_message(value: str) -> str:
        without_urls = re.sub(r"https?://\S+", "[URL OMITIDA]", str(value or ""))
        return without_urls[:1000]

    @staticmethod
    def validate_after_date(value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("La fecha no puede estar vacia.")
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("--after-date debe incluir zona horaria, por ejemplo +00:00.")
        return parsed.isoformat()
