from __future__ import annotations

from typing import Any

from services.balance_order_service import BalanceOrderService
from services.balance_payment_service import BalancePaymentService


DISPLAY_STATES = {
    "awaiting_payment": "Pendiente",
    "pending": "Pendiente",
    "paid": "Pagado",
    "processing": "Pagado",
    "completed": "Pagado",
    "credited": "Acreditado",
    "applied": "Acreditado",
    "cancelled": "Cancelado",
    "failed": "Fallido",
    "error": "Error",
}


class BalanceAdminService:
    def __init__(
        self,
        order_service: BalanceOrderService | None = None,
        payment_service: BalancePaymentService | None = None,
    ) -> None:
        self._order_service = order_service or BalanceOrderService()
        self._payment_service = payment_service or BalancePaymentService()

    def list_recent_loads(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
        order_id: int | None = None,
        refresh_remote: bool = False,
    ) -> list[dict[str, Any]]:
        rows = self._order_service.list_local_orders(limit=limit, order_id=order_id)
        results = [self._build_admin_row(row, refresh_remote=refresh_remote) for row in rows]
        if status and status != "Todos":
            normalized = status.casefold()
            results = [row for row in results if str(row["display_status"]).casefold() == normalized]
        return results

    def get_load_detail(self, order_id: int, *, refresh_remote: bool = False) -> dict[str, Any] | None:
        local_order = self._order_service.get_local_order(order_id)
        if not local_order:
            return None
        row = self._build_admin_row(local_order, refresh_remote=refresh_remote)
        local_load = self._order_service.get_local_load(f"WC-BALANCE-{order_id}") or {}
        return {
            **row,
            "reference": f"WC-BALANCE-{order_id}",
            "date_paid": row.get("date_paid") or local_order.get("paid_at"),
            "previous_balance": local_load.get("previous_balance"),
            "credited_amount": local_load.get("amount"),
            "new_balance": local_load.get("new_balance"),
            "recarga_id": local_load.get("recarga_id"),
            "historial_id": local_load.get("historial_id"),
            "admin_error": row.get("last_error") or local_load.get("last_error"),
            "monitor_info": {
                "local_status": row.get("local_status"),
                "paid": row.get("paid"),
                "credited": row.get("credited"),
                "can_credit": row.get("can_credit"),
                "reason": row.get("reason"),
            },
        }

    def _build_admin_row(self, local_order: dict[str, Any], *, refresh_remote: bool) -> dict[str, Any]:
        order_id = int(local_order["woocommerce_order_id"])
        check: dict[str, Any] = {}
        if refresh_remote:
            check = self._payment_service.check_order(order_id)

        client = self._payment_service.get_client_by_id(int(local_order["client_id"]))
        local_load = self._order_service.get_local_load(f"WC-BALANCE-{order_id}") or {}
        load_applied = str(local_load.get("status") or "") == "applied"
        local_status = str(check.get("local_status") or local_order.get("status") or "")
        if load_applied:
            local_status = "credited"
        wc_status = str(check.get("woocommerce_status") or "")
        credited = bool(check.get("credited") or load_applied or local_status == "credited")
        effective_status = "credited" if credited else local_status or wc_status
        return {
            "order_id": order_id,
            "date": local_order.get("created_at"),
            "client_id": int(local_order["client_id"]),
            "client_name": client.get("name") if client.get("ok") else f"Cliente {local_order['client_id']}",
            "dni_masked": self._mask_last4(str(local_order.get("dni_last4") or "")),
            "amount": str(check.get("amount") or local_order.get("amount") or ""),
            "payment_method": str(check.get("payment_method") or ""),
            "woocommerce_status": wc_status,
            "local_status": local_status,
            "display_status": self.display_status(effective_status),
            "credited": credited,
            "accreditation": "Si" if credited else "No",
            "last_error": check.get("message") or local_order.get("last_error") or local_load.get("last_error"),
            "date_paid": check.get("date_paid") or local_order.get("paid_at"),
            "paid": check.get("paid"),
            "can_credit": check.get("can_credit"),
            "reason": check.get("reason") or check.get("message"),
        }

    @staticmethod
    def display_status(value: str) -> str:
        normalized = str(value or "").strip().lower()
        return DISPLAY_STATES.get(normalized, normalized.replace("_", " ").title() or "Desconocido")

    @staticmethod
    def _mask_last4(last4: str) -> str:
        digits = "".join(char for char in last4 if char.isdigit())[-4:]
        return f"****{digits}" if digits else "-"
