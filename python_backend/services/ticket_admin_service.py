from __future__ import annotations

from pathlib import Path
from typing import Any

from integrations.woocommerce_client import WooCommerceClient
from services.delivery_state_service import DeliveryStateService
from services.order_monitor_service import DEBUG_DIR, OrderMonitorService
from services.ticket_delivery_service import TicketDeliveryService
from utils.phone_utils import mask_phone, normalize_argentine_phone


VISIBLE_STATES = {
    "detected": "Detectado",
    "waiting_payment": "Esperando pago",
    "waiting_ticket": "Esperando ticket",
    "awaiting_customer_confirmation": "Esperando confirmacion",
    "ready": "Listo",
    "sending": "Enviando",
    "sent": "Enviado",
    "retryable_error": "Error reintentable",
    "permanent_error": "Error permanente",
    "ignored": "Ignorado",
    "simulated": "Simulado",
    "already_sent": "Enviado",
}


class TicketAdminService:
    def __init__(
        self,
        delivery_state_service: DeliveryStateService | None = None,
        woocommerce_client: WooCommerceClient | None = None,
        ticket_delivery_service: TicketDeliveryService | None = None,
        order_monitor_service: OrderMonitorService | None = None,
    ) -> None:
        self._delivery_state_service = delivery_state_service or DeliveryStateService()
        self._woocommerce_client = woocommerce_client or WooCommerceClient()
        self._ticket_delivery_service = ticket_delivery_service or TicketDeliveryService()
        self._order_monitor_service = order_monitor_service or OrderMonitorService(
            woocommerce_client=self._woocommerce_client,
            ticket_delivery_service=self._ticket_delivery_service,
            delivery_state_service=self._delivery_state_service,
        )

    def list_recent_deliveries(
        self,
        *,
        limit: int = 100,
        status: str = "Todos",
        order_id: int | None = None,
        show_ignored: bool = False,
    ) -> list[dict[str, Any]]:
        raw_status = None if status == "Todos" else self._status_from_visible(status)
        states = self._delivery_state_service.list_recent(
            limit=limit,
            status=raw_status,
            order_id=order_id,
        )
        rows: list[dict[str, Any]] = []
        for state in states:
            if (
                not show_ignored
                and raw_status is None
                and str(state.get("status") or "") == "ignored"
            ):
                continue
            rows.append(self._build_row(state))
        return rows

    def get_delivery_detail(self, order_id: int, *, include_pdfs: bool = True) -> dict[str, Any]:
        state = self._delivery_state_service.get_order_state(order_id) or {}
        order = self._woocommerce_client.get_order(order_id)
        billing = order.get("billing") or {}
        original_phone = str(billing.get("phone") or "").strip()
        normalized_phone = normalize_argentine_phone(original_phone)
        delivery_info = self._ticket_delivery_service.get_order_delivery_info(order_id)
        manual_history = self._delivery_state_service.list_manual_resends(order_id)

        pdf_files: list[str] = []
        pdf_count = 0
        pdf_error = None
        if include_pdfs:
            preview_dir = DEBUG_DIR / f"admin_preview_{order_id}"
            prepared = self._ticket_delivery_service.prepare_order_tickets(order_id, preview_dir)
            pdf_files = list(prepared.get("pdf_files") or [])
            pdf_count = len(pdf_files)
            if not prepared.get("ready"):
                pdf_error = str(prepared.get("reason") or "")

        return {
            "order_id": order_id,
            "client_name": self._build_client_name(billing),
            "date": str(order.get("date_created") or state.get("first_seen_at") or ""),
            "original_phone": original_phone,
            "normalized_phone": normalized_phone,
            "masked_phone": mask_phone(normalized_phone or original_phone),
            "destination_phone": normalized_phone or original_phone,
            "expected_tickets": int(state.get("expected_tickets") or delivery_info.get("expected_tickets") or 0),
            "found_tickets": int(state.get("found_tickets") or 0),
            "sent_tickets": int(state.get("sent_tickets") or 0),
            "status": str(state.get("status") or ""),
            "display_status": self.display_status(state.get("status")),
            "last_sent_at": state.get("sent_at"),
            "customer_prompted_at": state.get("customer_prompted_at"),
            "last_error": state.get("last_error"),
            "payment_method": str(order.get("payment_method") or ""),
            "order_status": str(order.get("status") or ""),
            "pdf_files": pdf_files,
            "pdf_count": pdf_count,
            "pdf_error": pdf_error,
            "manual_history": manual_history,
        }

    def resend_tickets(self, order_id: int, destination_phone: str) -> dict[str, Any]:
        return self._order_monitor_service.resend_order_to_phone(order_id, destination_phone)

    def normalize_destination_phone(self, phone: str) -> str | None:
        return normalize_argentine_phone(phone)

    @staticmethod
    def display_status(raw_status: Any) -> str:
        return VISIBLE_STATES.get(str(raw_status or ""), str(raw_status or "-"))

    @staticmethod
    def _status_from_visible(label: str) -> str:
        normalized = str(label or "").strip().lower()
        for raw, display in VISIBLE_STATES.items():
            if display.lower() == normalized:
                return raw
        return normalized

    def _build_row(self, state: dict[str, Any]) -> dict[str, Any]:
        order_id = int(state.get("order_id") or 0)
        order = self._woocommerce_client.get_order(order_id)
        billing = order.get("billing") or {}
        original_phone = str(billing.get("phone") or "").strip()
        normalized_phone = str(state.get("phone_normalized") or normalize_argentine_phone(original_phone) or "")
        found = int(state.get("found_tickets") or 0)
        sent = int(state.get("sent_tickets") or 0)
        return {
            "order_id": order_id,
            "date": str(order.get("date_created") or state.get("first_seen_at") or ""),
            "client_name": self._build_client_name(billing),
            "original_phone": original_phone,
            "normalized_phone": normalized_phone,
            "expected_tickets": int(state.get("expected_tickets") or 0),
            "ticket_progress": f"{found}/{sent}",
            "found_tickets": found,
            "sent_tickets": sent,
            "status": str(state.get("status") or ""),
            "display_status": self.display_status(state.get("status")),
            "last_sent_at": state.get("sent_at"),
            "customer_prompted_at": state.get("customer_prompted_at"),
            "last_error": state.get("last_error"),
            "updated_at": state.get("updated_at"),
        }

    @staticmethod
    def _build_client_name(billing: dict[str, Any]) -> str:
        first_name = str(billing.get("first_name") or "").strip()
        last_name = str(billing.get("last_name") or "").strip()
        full_name = " ".join(part for part in (first_name, last_name) if part).strip()
        return full_name or "-"
