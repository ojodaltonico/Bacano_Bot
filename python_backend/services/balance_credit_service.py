from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from integrations.woocommerce_client import WooCommerceAPIError
from services.balance_load_service import BalanceLoadService
from services.balance_order_service import BalanceOrderService
from services.balance_payment_service import BalancePaymentService


class BalanceCreditService:
    def __init__(self) -> None:
        self._payment_service = BalancePaymentService()
        self._load_service = BalanceLoadService()
        self._order_service = BalanceOrderService()

    def preview_credit(self, order_id: int) -> dict[str, Any]:
        check = self._payment_service.check_order(order_id)
        if not check.get("ok"):
            return check

        if not check.get("paid"):
            return {
                "ok": False,
                "reason": "payment_not_confirmed",
                "message": check.get("reason") or "El pago no esta confirmado.",
                "check": check,
            }

        if check.get("credited"):
            return {
                "ok": False,
                "reason": "already_credited",
                "message": "El pedido ya fue acreditado.",
                "check": check,
            }

        if not check.get("can_credit"):
            return {
                "ok": False,
                "reason": "cannot_credit",
                "message": check.get("reason") or "El pedido no puede acreditarse.",
                "check": check,
            }

        client_lookup = self._payment_service._find_client_by_id(int(check["client_id"]))
        if not client_lookup.get("ok"):
            return {
                "ok": False,
                "reason": "client_not_found",
                "message": client_lookup.get("message") or "No se encontro el cliente interno.",
                "check": check,
            }

        return {
            "ok": True,
            "order_id": int(check["order_id"]),
            "client_id": int(check["client_id"]),
            "client_name": str(client_lookup.get("name") or ""),
            "dni": str(client_lookup.get("dni") or ""),
            "amount": str(check["amount"]),
            "reference": str(check["reference"]),
            "preview": check.get("preview"),
            "payment_method": str(check.get("payment_method") or ""),
            "woocommerce_status": str(check.get("woocommerce_status") or ""),
            "date_paid": check.get("date_paid"),
        }

    def apply_credit(self, order_id: int, confirmed_client_id: int) -> dict[str, Any]:
        preview = self.preview_credit(order_id)
        if not preview.get("ok"):
            return preview

        client_id = int(preview["client_id"])
        if int(confirmed_client_id) != client_id:
            return {
                "ok": False,
                "reason": "client_confirmation_mismatch",
                "message": "El ID confirmado no coincide con el cliente del pedido.",
            }

        result = self._load_service.apply_load(
            dni=str(preview["dni"]),
            amount=str(preview["amount"]),
            reference=str(preview["reference"]),
            confirmed_client_id=client_id,
        )
        if not result.get("ok"):
            return result

        credited_at = datetime.now(timezone.utc).isoformat()
        self._order_service.update_local_order_status(
            order_id,
            status="credited",
            credited_at=credited_at,
            last_error=None,
        )

        note_error = None
        try:
            self._order_service._woocommerce_client.create_order_note(
                order_id=order_id,
                note=(
                    "Carga de saldo acreditada automaticamente por Bacano Bot.\n"
                    f"Referencia: {preview['reference']}.\n"
                    f"Recarga ID: {result['recarga_id']}. Historial ID: {result['historial_id']}."
                ),
                customer_note=False,
            )
        except (WooCommerceAPIError, ValueError) as exc:
            note_error = str(exc)

        verification = self._load_service.verify_applied_load(
            client_id=client_id,
            recarga_id=int(result["recarga_id"]),
            historial_id=int(result["historial_id"]),
        )

        return {
            "ok": True,
            **result,
            "order_id": order_id,
            "credited_at": credited_at,
            "verification": verification,
            "woocommerce_note_error": note_error,
        }
