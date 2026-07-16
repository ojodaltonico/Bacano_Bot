from __future__ import annotations

from pathlib import Path
import time
from typing import Any

import requests

from integrations.woocommerce_client import WooCommerceClient
from services.delivery_state_service import DeliveryStateService
from services.order_classification import evaluate_ticket_order, meta_to_map
from services.ticket_delivery_service import TicketDeliveryService
from services.ticket_settings_service import TicketSettingsService
from utils.phone_utils import mask_phone, normalize_argentine_phone


DEBUG_DIR = Path(__file__).resolve().parent.parent / "debug"
ENDPOINT_URL = "http://127.0.0.1:3000/internal/send-document"
REQUEST_TIMEOUT = 30
MERCADO_PAGO_METHOD = "woo-mercado-pago-custom"


class OrderMonitorService:
    def __init__(
        self,
        woocommerce_client: WooCommerceClient | None = None,
        ticket_delivery_service: TicketDeliveryService | None = None,
        delivery_state_service: DeliveryStateService | None = None,
        settings_service: TicketSettingsService | None = None,
    ) -> None:
        self._woocommerce_client = woocommerce_client or WooCommerceClient()
        self._ticket_delivery_service = ticket_delivery_service or TicketDeliveryService()
        self._delivery_state_service = delivery_state_service or DeliveryStateService()
        self._settings_service = settings_service

    def scan_configured_orders(self, limit: int = 20) -> dict[str, Any]:
        settings_service = self._settings_service or TicketSettingsService()
        settings = settings_service.get_settings()
        if not settings["monitor_enabled"]:
            return {
                "mode": "disabled",
                "filters": {},
                "summary": self._build_summary([]),
                "results": [],
                "reason": "El monitor de entradas esta apagado.",
            }

        if settings["test_mode"]:
            test_phone = str(settings.get("test_phone") or "").strip()
            normalized_test_phone = self._normalize_argentine_phone(test_phone)
            if not normalized_test_phone:
                return {
                    "mode": "invalid_config",
                    "filters": {},
                    "summary": self._build_summary([]),
                    "results": [],
                    "reason": "Falta un telefono de prueba valido para el modo test.",
                }
            result = self.live_test_recent_orders(
                limit=limit,
                test_phone=normalized_test_phone,
                after_order_id=settings.get("monitor_after_order_id"),
                after_date=settings.get("monitor_after_date"),
            )
            result["mode"] = "live-test"
            result["filters"] = {
                "after_order_id": settings.get("monitor_after_order_id"),
                "after_date": settings.get("monitor_after_date"),
            }
            return result

        if settings["auto_send_customer"]:
            result = self.live_recent_orders(
                limit=limit,
                after_order_id=settings.get("monitor_after_order_id"),
                after_date=settings.get("monitor_after_date"),
            )
            result["mode"] = "live"
            result["filters"] = {
                "after_order_id": settings.get("monitor_after_order_id"),
                "after_date": settings.get("monitor_after_date"),
            }
            return result

        result = self.scan_recent_orders(
            limit=limit,
            dry_run=True,
            after_order_id=settings.get("monitor_after_order_id"),
            after_date=settings.get("monitor_after_date"),
        )
        result["mode"] = "dry-run"
        result["filters"] = {
            "after_order_id": settings.get("monitor_after_order_id"),
            "after_date": settings.get("monitor_after_date"),
        }
        return result

    def scan_recent_orders(
        self,
        limit: int = 20,
        dry_run: bool = True,
        after_order_id: int | None = None,
        after_date: str | None = None,
    ) -> dict[str, Any]:
        if limit <= 0:
            raise ValueError("limit debe ser mayor que 0.")

        orders = self._fetch_order_pages(
            page_size=min(limit, 100),
            limit=limit,
            after_order_id=after_order_id,
            after_date=after_date,
        )
        results: list[dict[str, Any]] = []

        for order in orders:
            order_id = self._safe_order_id(order)
            if after_order_id is not None and order_id <= after_order_id:
                continue
            try:
                result = self._scan_single_order(order, dry_run=dry_run)
            except Exception as exc:
                order_id = self._safe_order_id(order)
                self._delivery_state_service.mark_retryable_error(
                    order_id,
                    last_error=str(exc),
                    metadata_json={"summary": "error_durante_analisis"},
                )
                result = self._build_result(
                    order_id,
                    "retryable_error",
                    "error durante analisis",
                    changed=True,
                )
            results.append(result)

        return {
            "results": results,
            "summary": self._build_summary(results),
        }

    def live_test_recent_orders(
        self,
        limit: int,
        test_phone: str,
        after_order_id: int | None,
        after_date: str | None = None,
    ) -> dict[str, Any]:
        normalized_test_phone = self._normalize_argentine_phone(test_phone)
        if not normalized_test_phone:
            raise RuntimeError("El telefono de prueba no es valido.")

        orders = self._fetch_order_pages(
            page_size=min(limit, 100),
            limit=limit,
            after_order_id=after_order_id,
            after_date=after_date,
        )
        results: list[dict[str, Any]] = []

        for order in orders:
            order_id = self._safe_order_id(order)
            if after_order_id is not None and order_id <= after_order_id:
                continue
            try:
                result = self._live_test_single_order(order, normalized_test_phone)
            except Exception as exc:
                safe_error = str(exc) or "error durante analisis"
                self._delivery_state_service.mark_retryable_error(
                    order_id,
                    last_error=safe_error,
                    metadata_json={"summary": "error_durante_live_test"},
                )
                result = self._build_result(
                    order_id,
                    "retryable_error",
                    safe_error,
                    changed=True,
                )
            results.append(result)

        return {
            "results": results,
            "summary": self._build_summary(results),
        }

    def live_recent_orders(
        self,
        limit: int,
        after_order_id: int | None,
        after_date: str | None = None,
    ) -> dict[str, Any]:
        orders = self._fetch_order_pages(
            page_size=min(limit, 100),
            limit=limit,
            after_order_id=after_order_id,
            after_date=after_date,
        )
        results: list[dict[str, Any]] = []

        for order in orders:
            order_id = self._safe_order_id(order)
            if after_order_id is not None and order_id <= after_order_id:
                continue
            try:
                result = self._live_single_order(order)
            except Exception as exc:
                safe_error = str(exc) or "error durante analisis"
                self._delivery_state_service.mark_retryable_error(
                    order_id,
                    last_error=safe_error,
                    metadata_json={"summary": "error_durante_live"},
                )
                result = self._build_result(
                    order_id,
                    "retryable_error",
                    safe_error,
                    changed=True,
                    payment_method=str(order.get("payment_method") or ""),
                    masked_destination="",
                    sent_tickets=0,
                )
            results.append(result)

        return {
            "results": results,
            "summary": self._build_summary(results),
        }

    def send_order_for_test(
        self, order_id: int, test_phone: str, force: bool = False
    ) -> dict[str, Any]:
        delivery_info = self._ticket_delivery_service.get_order_delivery_info(order_id)
        state = self._delivery_state_service.get_order_state(order_id)

        normalized_test_phone = self._normalize_argentine_phone(test_phone)
        if not normalized_test_phone:
            return {
                "ok": False,
                "order_id": order_id,
                "reason": "Telefono de prueba invalido.",
            }

        normalized_billing_phone = self._normalize_argentine_phone(
            delivery_info.get("billing_phone")
        )
        masked_billing_phone = mask_phone(normalized_billing_phone or delivery_info.get("billing_phone"))
        billing_phone_present = bool(delivery_info.get("billing_phone"))
        billing_phone_normalizable = bool(normalized_billing_phone)
        if force and normalized_billing_phone and normalized_test_phone == normalized_billing_phone:
            return {
                "ok": False,
                "order_id": order_id,
                "reason": "No se permite --force usando el telefono real de facturacion.",
            }

        if self._delivery_state_service.has_been_sent(order_id) and not force:
            return {
                "ok": False,
                "order_id": order_id,
                "already_sent": True,
                "reason": "Pedido ya enviado",
            }

        destination_dir = DEBUG_DIR / f"delivery_test_{order_id}"
        prepare_result = self._ticket_delivery_service.prepare_order_tickets(
            order_id, destination_dir
        )
        if not prepare_result.get("ready"):
            return {
                "ok": False,
                "order_id": order_id,
                "already_sent": False,
                "reason": prepare_result.get("reason") or "Pedido no listo para enviar.",
                "status": prepare_result.get("status"),
                "payment_method": prepare_result.get("payment_method"),
                "date_paid": prepare_result.get("date_paid"),
                "needs_payment": prepare_result.get("needs_payment"),
                "billing_phone_present": prepare_result.get("billing_phone_present"),
                "billing_phone_normalizable": billing_phone_normalizable,
                "masked_real_destination": masked_billing_phone,
                "expected_tickets": prepare_result.get("expected_tickets", 0),
                "found_tickets": prepare_result.get("found_tickets", 0),
                "not_ready_reasons": prepare_result.get("not_ready_reasons") or [],
            }

        ticket_pdfs = prepare_result.get("ticket_pdfs") or []
        if not ticket_pdfs:
            return {
                "ok": False,
                "order_id": order_id,
                "already_sent": False,
                "reason": "No hay tickets PDF para enviar.",
                "expected_tickets": prepare_result.get("expected_tickets", 0),
                "found_tickets": prepare_result.get("found_tickets", 0),
                "billing_phone_present": billing_phone_present,
                "billing_phone_normalizable": billing_phone_normalizable,
                "masked_real_destination": masked_billing_phone,
            }

        self._delivery_state_service.mark_sending(
            order_id,
            payment_method=delivery_info.get("payment_method"),
            order_status=delivery_info.get("status"),
            expected_tickets=int(prepare_result.get("expected_tickets") or 0),
            found_tickets=int(prepare_result.get("found_tickets") or 0),
            phone_normalized=normalized_test_phone,
            metadata_json={"summary": "sending_test"},
        )

        send_results: list[dict[str, Any]] = []
        total = len(ticket_pdfs)
        for index, ticket_pdf in enumerate(ticket_pdfs, start=1):
            pdf_path = Path(ticket_pdf["pdf_path"])
            caption = self._build_caption(ticket_pdf, index, total)
            ok, detail = self._send_pdf_to_bot(
                normalized_test_phone,
                pdf_path,
                pdf_path.name,
                caption,
            )
            send_results.append(
                {
                    "index": index,
                    "ok": ok,
                    "filename": pdf_path.name,
                    "detail": detail,
                }
            )
            if not ok:
                self._delivery_state_service.mark_retryable_error(
                    order_id,
                    payment_method=delivery_info.get("payment_method"),
                    order_status=delivery_info.get("status"),
                    expected_tickets=int(prepare_result.get("expected_tickets") or 0),
                    found_tickets=int(prepare_result.get("found_tickets") or 0),
                    sent_tickets=sum(1 for item in send_results if item["ok"]),
                    phone_normalized=normalized_test_phone,
                    last_error=detail,
                    metadata_json={"summary": "document send failed"},
                )
                return {
                    "ok": False,
                    "order_id": order_id,
                    "already_sent": False,
                    "ready": True,
                    "expected_tickets": prepare_result.get("expected_tickets", 0),
                    "found_tickets": prepare_result.get("found_tickets", 0),
                    "sent_tickets": sum(1 for item in send_results if item["ok"]),
                    "results": send_results,
                    "reason": detail,
                    "state_saved": "retryable_error",
                    "billing_phone_present": billing_phone_present,
                    "billing_phone_normalizable": billing_phone_normalizable,
                    "masked_real_destination": masked_billing_phone,
                }
            if index < total:
                time.sleep(1)

        previous_attempts = int(state.get("attempt_count") or 0) if state else 0
        self._delivery_state_service.mark_sent(
            order_id,
            payment_method=delivery_info.get("payment_method"),
            order_status=delivery_info.get("status"),
            expected_tickets=int(prepare_result.get("expected_tickets") or 0),
            found_tickets=int(prepare_result.get("found_tickets") or 0),
            sent_tickets=total,
            phone_normalized=normalized_test_phone,
            attempt_count=previous_attempts + 1,
            last_error=None,
            metadata_json={"summary": "manual test send"},
        )
        return {
            "ok": True,
            "order_id": order_id,
            "already_sent": False,
            "ready": True,
            "expected_tickets": prepare_result.get("expected_tickets", 0),
            "found_tickets": prepare_result.get("found_tickets", 0),
            "sent_tickets": total,
            "results": send_results,
            "state_saved": "sent",
            "billing_phone_present": billing_phone_present,
            "billing_phone_normalizable": billing_phone_normalizable,
            "masked_real_destination": masked_billing_phone,
        }

    def send_order_to_customer(self, order_id: int) -> dict[str, Any]:
        delivery_info = self._ticket_delivery_service.get_order_delivery_info(order_id)
        state = self._delivery_state_service.get_order_state(order_id)
        raw_billing_phone = delivery_info.get("billing_phone")
        normalized_billing_phone = self._normalize_argentine_phone(raw_billing_phone)
        masked_billing_phone = mask_phone(normalized_billing_phone or raw_billing_phone)
        billing_phone_present = bool(str(raw_billing_phone or "").strip())
        billing_phone_normalizable = bool(normalized_billing_phone)

        if self._delivery_state_service.has_been_sent(order_id):
            return {
                "ok": False,
                "order_id": order_id,
                "already_sent": True,
                "reason": "Pedido ya enviado",
                "billing_phone_present": billing_phone_present,
                "billing_phone_normalizable": billing_phone_normalizable,
                "masked_destination": masked_billing_phone,
            }

        if not billing_phone_normalizable:
            self._delivery_state_service.mark_permanent_error(
                order_id,
                payment_method=delivery_info.get("payment_method"),
                order_status=delivery_info.get("status"),
                expected_tickets=int(delivery_info.get("expected_tickets") or 0),
                found_tickets=0,
                sent_tickets=0,
                phone_normalized=None,
                last_error="invalid_phone",
                metadata_json={"summary": "invalid_phone"},
            )
            return {
                "ok": False,
                "order_id": order_id,
                "already_sent": False,
                "reason": "invalid_phone",
                "status": delivery_info.get("status"),
                "payment_method": delivery_info.get("payment_method"),
                "expected_tickets": int(delivery_info.get("expected_tickets") or 0),
                "found_tickets": 0,
                "sent_tickets": 0,
                "billing_phone_present": billing_phone_present,
                "billing_phone_normalizable": False,
                "masked_destination": masked_billing_phone,
                "state_saved": "permanent_error",
            }

        previous_prompted = bool(state and state.get("status") == "awaiting_customer_confirmation")
        if previous_prompted:
            return {
                "ok": False,
                "order_id": order_id,
                "already_prompted": True,
                "reason": "awaiting_customer_confirmation",
                "status": delivery_info.get("status"),
                "payment_method": delivery_info.get("payment_method"),
                "expected_tickets": int(delivery_info.get("expected_tickets") or 0),
                "found_tickets": int(state.get("found_tickets") or 0),
                "sent_tickets": int(state.get("sent_tickets") or 0),
                "billing_phone_present": billing_phone_present,
                "billing_phone_normalizable": True,
                "masked_destination": masked_billing_phone,
            }

        destination_dir = DEBUG_DIR / f"delivery_live_intro_{order_id}"
        prepare_result = self._ticket_delivery_service.prepare_order_tickets(
            order_id, destination_dir
        )
        if not prepare_result.get("ready"):
            return {
                "ok": False,
                "order_id": order_id,
                "already_sent": False,
                "reason": prepare_result.get("reason") or "Pedido no listo para enviar.",
                "status": prepare_result.get("status"),
                "payment_method": prepare_result.get("payment_method"),
                "expected_tickets": prepare_result.get("expected_tickets", 0),
                "found_tickets": prepare_result.get("found_tickets", 0),
                "sent_tickets": 0,
                "billing_phone_present": billing_phone_present,
                "billing_phone_normalizable": True,
                "masked_destination": masked_billing_phone,
                "not_ready_reasons": prepare_result.get("not_ready_reasons") or [],
            }

        ticket_pdfs = prepare_result.get("ticket_pdfs") or []
        if not ticket_pdfs:
            return {
                "ok": False,
                "order_id": order_id,
                "already_sent": False,
                "reason": "No hay tickets PDF para enviar.",
                "status": delivery_info.get("status"),
                "payment_method": delivery_info.get("payment_method"),
                "expected_tickets": prepare_result.get("expected_tickets", 0),
                "found_tickets": prepare_result.get("found_tickets", 0),
                "sent_tickets": 0,
                "billing_phone_present": billing_phone_present,
                "billing_phone_normalizable": True,
                "masked_destination": masked_billing_phone,
            }

        intro_message = self._build_customer_intro_confirmation_message(
            prepare_result.get("ticket_pdfs") or [],
            int(prepare_result.get("expected_tickets") or 0),
        )
        ok, detail = self._send_text_to_bot(normalized_billing_phone, intro_message)
        if not ok:
            self._delivery_state_service.mark_retryable_error(
                order_id,
                payment_method=delivery_info.get("payment_method"),
                order_status=delivery_info.get("status"),
                expected_tickets=int(prepare_result.get("expected_tickets") or 0),
                found_tickets=int(prepare_result.get("found_tickets") or 0),
                sent_tickets=0,
                phone_normalized=normalized_billing_phone,
                last_error=detail,
                metadata_json={"summary": "intro send failed"},
            )
            return {
                "ok": False,
                "order_id": order_id,
                "already_sent": False,
                "reason": detail,
                "status": delivery_info.get("status"),
                "payment_method": delivery_info.get("payment_method"),
                "expected_tickets": prepare_result.get("expected_tickets", 0),
                "found_tickets": prepare_result.get("found_tickets", 0),
                "sent_tickets": 0,
                "billing_phone_present": billing_phone_present,
                "billing_phone_normalizable": True,
                "masked_destination": masked_billing_phone,
                "state_saved": "retryable_error",
            }

        self._delivery_state_service.mark_awaiting_customer_confirmation(
            order_id,
            payment_method=delivery_info.get("payment_method"),
            order_status=delivery_info.get("status"),
            expected_tickets=int(prepare_result.get("expected_tickets") or 0),
            found_tickets=int(prepare_result.get("found_tickets") or 0),
            sent_tickets=0,
            phone_normalized=normalized_billing_phone,
            last_error=None,
            metadata_json={"summary": "awaiting_customer_confirmation"},
        )
        return {
            "ok": True,
            "order_id": order_id,
            "already_sent": False,
            "awaiting_customer_confirmation": True,
            "status": delivery_info.get("status"),
            "payment_method": delivery_info.get("payment_method"),
            "expected_tickets": prepare_result.get("expected_tickets", 0),
            "found_tickets": prepare_result.get("found_tickets", 0),
            "sent_tickets": 0,
            "billing_phone_present": billing_phone_present,
            "billing_phone_normalizable": True,
            "masked_destination": masked_billing_phone,
            "state_saved": "awaiting_customer_confirmation",
        }

    def resend_order_to_phone(self, order_id: int, destination_phone: str) -> dict[str, Any]:
        delivery_info = self._ticket_delivery_service.get_order_delivery_info(order_id)
        original_phone = str(delivery_info.get("billing_phone") or "").strip()
        normalized_destination = self._normalize_argentine_phone(destination_phone)
        masked_destination = mask_phone(normalized_destination or destination_phone)

        if not normalized_destination:
            self._delivery_state_service.record_manual_resend(
                order_id,
                destination_phone=str(destination_phone or "").strip(),
                original_phone=original_phone or None,
                normalized_phone=None,
                sent_tickets=0,
                status="invalid_phone",
                error_detail="invalid_phone",
                metadata_json={"summary": "manual_resend_invalid_phone"},
            )
            return {
                "ok": False,
                "order_id": order_id,
                "reason": "invalid_phone",
                "masked_destination": masked_destination,
                "normalized_destination": None,
                "sent_tickets": 0,
            }

        destination_dir = DEBUG_DIR / f"delivery_manual_{order_id}_{int(time.time())}"
        prepare_result = self._ticket_delivery_service.prepare_order_tickets(order_id, destination_dir)
        if not prepare_result.get("ready"):
            message = str(prepare_result.get("reason") or "Pedido no listo para reenviar.")
            self._delivery_state_service.record_manual_resend(
                order_id,
                destination_phone=str(destination_phone or "").strip(),
                original_phone=original_phone or None,
                normalized_phone=normalized_destination,
                sent_tickets=0,
                status="not_ready",
                error_detail=message,
                metadata_json={
                    "summary": "manual_resend_not_ready",
                    "not_ready_reasons": prepare_result.get("not_ready_reasons") or [],
                },
            )
            return {
                "ok": False,
                "order_id": order_id,
                "reason": message,
                "masked_destination": masked_destination,
                "normalized_destination": normalized_destination,
                "sent_tickets": 0,
                "expected_tickets": int(prepare_result.get("expected_tickets") or 0),
                "found_tickets": int(prepare_result.get("found_tickets") or 0),
            }

        ticket_pdfs = prepare_result.get("ticket_pdfs") or []
        if not ticket_pdfs:
            self._delivery_state_service.record_manual_resend(
                order_id,
                destination_phone=str(destination_phone or "").strip(),
                original_phone=original_phone or None,
                normalized_phone=normalized_destination,
                sent_tickets=0,
                status="error",
                error_detail="No hay tickets PDF para reenviar.",
                metadata_json={"summary": "manual_resend_without_pdfs"},
            )
            return {
                "ok": False,
                "order_id": order_id,
                "reason": "No hay tickets PDF para reenviar.",
                "masked_destination": masked_destination,
                "normalized_destination": normalized_destination,
                "sent_tickets": 0,
                "expected_tickets": int(prepare_result.get("expected_tickets") or 0),
                "found_tickets": int(prepare_result.get("found_tickets") or 0),
            }

        send_results: list[dict[str, Any]] = []
        total = len(ticket_pdfs)
        for index, ticket_pdf in enumerate(ticket_pdfs, start=1):
            pdf_path = Path(ticket_pdf["pdf_path"])
            caption = self._build_customer_caption(ticket_pdf, index, total)
            if index == 1:
                caption = f"{self._build_customer_intro_message()}\n\n{caption}"
            ok, detail = self._send_pdf_to_bot(
                normalized_destination,
                pdf_path,
                pdf_path.name,
                caption,
            )
            send_results.append(
                {
                    "index": index,
                    "ok": ok,
                    "filename": pdf_path.name,
                    "detail": detail,
                }
            )
            if not ok:
                sent_count = sum(1 for item in send_results if item["ok"])
                self._delivery_state_service.record_manual_resend(
                    order_id,
                    destination_phone=str(destination_phone or "").strip(),
                    original_phone=original_phone or None,
                    normalized_phone=normalized_destination,
                    sent_tickets=sent_count,
                    status="error",
                    error_detail=detail,
                    metadata_json={"summary": "manual_resend_failed"},
                )
                return {
                    "ok": False,
                    "order_id": order_id,
                    "reason": detail,
                    "masked_destination": masked_destination,
                    "normalized_destination": normalized_destination,
                    "sent_tickets": sent_count,
                    "expected_tickets": int(prepare_result.get("expected_tickets") or 0),
                    "found_tickets": int(prepare_result.get("found_tickets") or 0),
                    "results": send_results,
                }
            if index < total:
                time.sleep(1)

        self._delivery_state_service.record_manual_resend(
            order_id,
            destination_phone=str(destination_phone or "").strip(),
            original_phone=original_phone or None,
            normalized_phone=normalized_destination,
            sent_tickets=total,
            status="sent",
            error_detail=None,
            metadata_json={"summary": "manual_resend_sent"},
        )
        return {
            "ok": True,
            "order_id": order_id,
            "normalized_destination": normalized_destination,
            "masked_destination": masked_destination,
            "sent_tickets": total,
            "expected_tickets": int(prepare_result.get("expected_tickets") or 0),
            "found_tickets": int(prepare_result.get("found_tickets") or 0),
            "results": send_results,
        }

    def confirm_pending_customer_deliveries(self, phone: str, message: str) -> dict[str, Any]:
        normalized_phone = self._normalize_argentine_phone(phone)
        if not normalized_phone:
            return {"handled": False, "reason": "invalid_phone"}
        if not self._is_affirmative_message(message):
            return {"handled": False, "reason": "not_affirmative"}

        pending_orders = self._delivery_state_service.list_pending_customer_confirmations(
            normalized_phone
        )
        if not pending_orders:
            return {"handled": False, "reason": "no_pending_deliveries"}

        results: list[dict[str, Any]] = []
        sent_orders = 0
        sent_tickets = 0
        for pending in pending_orders:
            order_id = int(pending.get("order_id") or 0)
            result = self._deliver_confirmed_order_to_customer(order_id, normalized_phone)
            results.append(result)
            if result.get("ok"):
                sent_orders += 1
                sent_tickets += int(result.get("sent_tickets") or 0)

        if sent_orders <= 0:
            return {
                "handled": True,
                "reply": "Todavia no pude enviarte las entradas. Intenta de nuevo en unos minutos, por favor.",
                "results": results,
            }

        plural = "s" if sent_orders != 1 else ""
        return {
            "handled": True,
            "reply": f"Listo. Ya te enviamos {sent_tickets} entrada(s) correspondiente{plural} a {sent_orders} compra(s).",
            "results": results,
        }

    def _fetch_order_pages(
        self,
        *,
        page_size: int,
        limit: int,
        after_order_id: int | None,
        after_date: str | None = None,
    ) -> list[dict[str, Any]]:
        seen_ids: set[int] = set()
        orders: list[dict[str, Any]] = []
        page = 1

        while True:
            page_orders = self._woocommerce_client.get_orders(
                per_page=page_size,
                page=page,
                after=after_date,
            )
            if not isinstance(page_orders, list):
                raise RuntimeError("WooCommerce no devolvio una lista de pedidos recientes.")
            if not page_orders:
                break

            valid_page_ids: list[int] = []
            for item in page_orders:
                if not isinstance(item, dict):
                    continue
                order_id = self._safe_order_id(item)
                if not order_id:
                    continue
                valid_page_ids.append(order_id)
                if order_id in seen_ids:
                    continue
                seen_ids.add(order_id)
                orders.append(item)

            if len(page_orders) < page_size:
                break
            if after_order_id is None and after_date is None and len(orders) >= limit:
                break
            if after_order_id is not None and valid_page_ids and all(order_id <= after_order_id for order_id in valid_page_ids):
                break
            page += 1

        orders.sort(key=lambda order: self._safe_order_id(order))
        if after_order_id is None and after_date is None:
            return orders[-limit:]
        if after_order_id is not None:
            orders = [
                order for order in orders
                if self._safe_order_id(order) > after_order_id
            ]
        return orders

    def _scan_single_order(self, order: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        order_id = self._safe_order_id(order)
        payment_method = str(order.get("payment_method") or "")
        order_status = str(order.get("status") or "")
        meta = meta_to_map(order.get("meta_data"))
        ticket_order = evaluate_ticket_order(order, meta)
        previous_state = self._delivery_state_service.get_order_state(order_id)
        billing = order.get("billing") or {}
        client_name = " ".join(
            part for part in (
                str(billing.get("first_name") or "").strip(),
                str(billing.get("last_name") or "").strip(),
            ) if part
        ).strip() or "-"

        if self._delivery_state_service.has_been_sent(order_id):
            return self._build_result(
                order_id,
                "already_sent",
                "ya enviado",
                changed=False,
            )

        self._delivery_state_service.mark_detected(
            order_id,
            payment_method=payment_method,
            order_status=order_status,
            expected_tickets=int(ticket_order.get("expected_tickets") or 0),
            order_date=str(order.get("date_created") or ""),
            client_name=client_name,
            original_phone=str(billing.get("phone") or "").strip(),
            metadata_json={"summary": "detected"},
        )

        exclusion_reasons = set(ticket_order.get("exclusion_reasons") or [])
        if "balance_load_operation" in exclusion_reasons:
            return self._mark_ignored(
                order_id,
                previous_state,
                payment_method,
                order_status,
                "pedido de carga de saldo",
            )
        if "no_ticket_quantity" in exclusion_reasons:
            return self._mark_ignored(
                order_id,
                previous_state,
                payment_method,
                order_status,
                "sin entradas reales",
            )
        if "missing_tickera_evidence" in exclusion_reasons:
            return self._mark_ignored(
                order_id,
                previous_state,
                payment_method,
                order_status,
                "sin evidencia suficiente de Tickera",
            )

        if payment_method == "cod":
            return self._mark_ignored(
                order_id,
                previous_state,
                payment_method,
                order_status,
                "efectivo/RRPP",
            )

        if payment_method != MERCADO_PAGO_METHOD:
            return self._mark_ignored(
                order_id,
                previous_state,
                payment_method,
                order_status,
                "metodo no habilitado",
            )

        if order_status in {"cancelled", "refunded", "failed"}:
            return self._mark_ignored(
                order_id,
                previous_state,
                payment_method,
                order_status,
                f"estado {order_status}",
            )

        delivery_info = self._ticket_delivery_service.get_order_delivery_info(order_id)
        normalized_phone = self._normalize_argentine_phone(delivery_info.get("billing_phone"))
        phone_valid = bool(normalized_phone)
        expected_tickets = int(delivery_info.get("expected_tickets") or 0)
        waiting_reasons = set(delivery_info.get("not_ready_reasons") or [])

        if {"payment_not_confirmed", "still_needs_payment", "status_not_ready"} & waiting_reasons:
            summary = self._build_waiting_payment_summary(waiting_reasons, order_status)
            self._delivery_state_service.mark_waiting_payment(
                order_id,
                payment_method=payment_method,
                order_status=order_status,
                expected_tickets=expected_tickets,
                phone_normalized=normalized_phone,
                metadata_json={"summary": summary, "phone_valid": phone_valid},
            )
            return self._build_result(
                order_id,
                "waiting_payment",
                summary,
                expected_tickets=expected_tickets,
                phone_valid=phone_valid,
                changed=self._did_result_change(
                    previous_state, "waiting_payment", expected_tickets, 0, phone_valid
                ),
            )

        if "missing_phone" in waiting_reasons:
            summary = "telefono no normalizable"
            self._delivery_state_service.mark_permanent_error(
                order_id,
                payment_method=payment_method,
                order_status=order_status,
                expected_tickets=expected_tickets,
                phone_normalized=normalized_phone,
                last_error=summary,
                metadata_json={"summary": summary, "phone_valid": phone_valid},
            )
            return self._build_result(
                order_id,
                "permanent_error",
                summary,
                expected_tickets=expected_tickets,
                phone_valid=phone_valid,
                changed=self._did_result_change(
                    previous_state, "permanent_error", expected_tickets, 0, phone_valid
                ),
            )

        if (
            dry_run
            and previous_state
            and previous_state.get("status") == "simulated"
            and previous_state.get("payment_method") == payment_method
            and previous_state.get("order_status") == order_status
            and int(previous_state.get("expected_tickets") or 0) == expected_tickets
            and int(previous_state.get("found_tickets") or 0) >= expected_tickets
            and phone_valid == bool(previous_state.get("phone_normalized"))
        ):
            self._delivery_state_service.mark_simulated(
                order_id,
                payment_method=payment_method,
                order_status=order_status,
                expected_tickets=expected_tickets,
                found_tickets=int(previous_state.get("found_tickets") or 0),
                phone_normalized=previous_state.get("phone_normalized"),
                metadata_json={"summary": "sin cambios", "phone_valid": phone_valid},
            )
            return self._build_result(
                order_id,
                "simulated",
                "sin cambios",
                expected_tickets=expected_tickets,
                found_tickets=int(previous_state.get("found_tickets") or 0),
                phone_valid=phone_valid,
                changed=False,
            )

        simulated_dir = DEBUG_DIR / f"monitor_simulation_{order_id}"
        prepare_result = self._ticket_delivery_service.prepare_order_tickets(order_id, simulated_dir)
        found_tickets = int(prepare_result.get("found_tickets") or 0)

        if not prepare_result.get("ready"):
            return self._handle_not_ready_prepare_result(
                order_id=order_id,
                previous_state=previous_state,
                payment_method=payment_method,
                order_status=order_status,
                expected_tickets=expected_tickets,
                found_tickets=found_tickets,
                phone_valid=phone_valid,
                normalized_phone=normalized_phone,
                prepare_result=prepare_result,
            )

        if dry_run:
            self._delivery_state_service.mark_simulated(
                order_id,
                payment_method=payment_method,
                order_status=order_status,
                expected_tickets=expected_tickets,
                found_tickets=found_tickets,
                phone_normalized=normalized_phone,
                metadata_json={"summary": "Mercado Pago confirmado", "phone_valid": phone_valid},
            )
            return self._build_result(
                order_id,
                "simulated",
                "Mercado Pago confirmado",
                expected_tickets=expected_tickets,
                found_tickets=found_tickets,
                phone_valid=phone_valid,
                changed=self._did_result_change(
                    previous_state, "simulated", expected_tickets, found_tickets, phone_valid
                ),
            )

        self._delivery_state_service.mark_ready(
            order_id,
            payment_method=payment_method,
            order_status=order_status,
            expected_tickets=expected_tickets,
            found_tickets=found_tickets,
            phone_normalized=normalized_phone,
            metadata_json={"summary": "ready", "phone_valid": phone_valid},
        )
        return self._build_result(
            order_id,
            "ready",
            "listo",
            expected_tickets=expected_tickets,
            found_tickets=found_tickets,
            phone_valid=phone_valid,
            changed=self._did_result_change(
                previous_state, "ready", expected_tickets, found_tickets, phone_valid
            ),
        )

    def _handle_not_ready_prepare_result(
        self,
        *,
        order_id: int,
        previous_state: dict[str, Any] | None,
        payment_method: str,
        order_status: str,
        expected_tickets: int,
        found_tickets: int,
        phone_valid: bool,
        normalized_phone: str | None,
        prepare_result: dict[str, Any],
    ) -> dict[str, Any]:
        reasons = set(prepare_result.get("not_ready_reasons") or [])
        summary = str(prepare_result.get("reason") or "tickets no listos")

        if "ticket_not_generated" in reasons:
            self._delivery_state_service.mark_waiting_ticket(
                order_id,
                payment_method=payment_method,
                order_status=order_status,
                expected_tickets=expected_tickets,
                found_tickets=found_tickets,
                phone_normalized=normalized_phone,
                metadata_json={"summary": summary, "phone_valid": phone_valid},
            )
            return self._build_result(
                order_id,
                "waiting_ticket",
                summary,
                expected_tickets=expected_tickets,
                found_tickets=found_tickets,
                phone_valid=phone_valid,
                changed=self._did_result_change(
                    previous_state, "waiting_ticket", expected_tickets, found_tickets, phone_valid
                ),
            )

        self._delivery_state_service.mark_retryable_error(
            order_id,
            payment_method=payment_method,
            order_status=order_status,
            expected_tickets=expected_tickets,
            found_tickets=found_tickets,
            phone_normalized=normalized_phone,
            last_error=summary,
            metadata_json={"summary": summary, "phone_valid": phone_valid},
        )
        return self._build_result(
            order_id,
            "retryable_error",
            summary,
            expected_tickets=expected_tickets,
            found_tickets=found_tickets,
            phone_valid=phone_valid,
            changed=self._did_result_change(
                previous_state, "retryable_error", expected_tickets, found_tickets, phone_valid
            ),
        )

    def _mark_ignored(
        self,
        order_id: int,
        previous_state: dict[str, Any] | None,
        payment_method: str,
        order_status: str,
        summary: str,
    ) -> dict[str, Any]:
        self._delivery_state_service.mark_ignored(
            order_id,
            payment_method=payment_method,
            order_status=order_status,
            metadata_json={"summary": summary},
        )
        return self._build_result(
            order_id,
            "ignored",
            summary,
            changed=self._did_result_change(previous_state, "ignored", 0, 0, False),
        )

    def _live_test_single_order(
        self, order: dict[str, Any], normalized_test_phone: str
    ) -> dict[str, Any]:
        dry_run_result = self._scan_single_order(order, dry_run=True)
        order_id = self._safe_order_id(order)

        if dry_run_result["status"] in {"already_sent", "ignored", "waiting_payment", "waiting_ticket"}:
            return {**dry_run_result, "changed": dry_run_result.get("changed", False)}
        if dry_run_result["status"] in {"retryable_error", "permanent_error"}:
            return dry_run_result

        send_result = self.send_order_for_test(order_id, normalized_test_phone, force=False)
        if send_result.get("already_sent"):
            return self._build_result(order_id, "already_sent", "ya enviado", changed=False)

        if send_result.get("ok"):
            return self._build_result(
                order_id,
                "sent",
                "enviado a telefono de prueba",
                expected_tickets=int(send_result.get("expected_tickets") or 0),
                found_tickets=int(send_result.get("found_tickets") or 0),
                phone_valid=True,
                changed=True,
                billing_phone_present=bool(send_result.get("billing_phone_present")),
                billing_phone_normalizable=bool(send_result.get("billing_phone_normalizable")),
                masked_real_destination=str(send_result.get("masked_real_destination") or ""),
            )

        state_status = "retryable_error"
        if send_result.get("reason") == "invalid_phone":
            state_status = "permanent_error"
        return self._build_result(
            order_id,
            state_status,
            str(send_result.get("reason") or "Error en envio de prueba."),
            expected_tickets=int(send_result.get("expected_tickets") or 0),
            found_tickets=int(send_result.get("found_tickets") or 0),
            phone_valid=True,
            changed=True,
            billing_phone_present=bool(send_result.get("billing_phone_present")),
            billing_phone_normalizable=bool(send_result.get("billing_phone_normalizable")),
            masked_real_destination=str(send_result.get("masked_real_destination") or ""),
        )

    def _live_single_order(self, order: dict[str, Any]) -> dict[str, Any]:
        order_id = self._safe_order_id(order)
        payment_method = str(order.get("payment_method") or "")
        delivery_info = self._ticket_delivery_service.get_order_delivery_info(order_id)
        normalized_billing_phone = self._normalize_argentine_phone(delivery_info.get("billing_phone"))
        masked_destination = mask_phone(normalized_billing_phone or delivery_info.get("billing_phone"))
        previous_state = self._delivery_state_service.get_order_state(order_id)

        if previous_state and previous_state.get("status") == "awaiting_customer_confirmation":
            return self._build_result(
                order_id,
                "awaiting_customer_confirmation",
                "esperando confirmacion del cliente",
                expected_tickets=int(previous_state.get("expected_tickets") or 0),
                found_tickets=int(previous_state.get("found_tickets") or 0),
                phone_valid=bool(normalized_billing_phone),
                changed=False,
                payment_method=payment_method,
                masked_destination=masked_destination,
                sent_tickets=0,
            )

        dry_run_result = self._scan_single_order(order, dry_run=True)

        if dry_run_result["status"] == "already_sent":
            return {
                **dry_run_result,
                "payment_method": payment_method,
                "masked_destination": masked_destination,
                "sent_tickets": 0,
                "changed": False,
            }

        if dry_run_result["status"] in {
            "ignored",
            "waiting_payment",
            "waiting_ticket",
            "retryable_error",
            "permanent_error",
        }:
            return {
                **dry_run_result,
                "payment_method": payment_method,
                "masked_destination": masked_destination,
                "sent_tickets": 0,
            }

        send_result = self.send_order_to_customer(order_id)
        if send_result.get("already_sent"):
            return self._build_result(
                order_id,
                "already_sent",
                "ya enviado",
                expected_tickets=int(send_result.get("expected_tickets") or 0),
                found_tickets=int(send_result.get("found_tickets") or 0),
                phone_valid=True,
                changed=False,
                payment_method=payment_method,
                masked_destination=str(send_result.get("masked_destination") or masked_destination),
                sent_tickets=0,
            )

        if send_result.get("ok"):
            return self._build_result(
                order_id,
                "awaiting_customer_confirmation",
                "mensaje inicial enviado",
                expected_tickets=int(send_result.get("expected_tickets") or 0),
                found_tickets=int(send_result.get("found_tickets") or 0),
                phone_valid=True,
                changed=True,
                payment_method=payment_method,
                masked_destination=str(send_result.get("masked_destination") or masked_destination),
                sent_tickets=0,
            )

        result_status = "retryable_error"
        if send_result.get("reason") == "invalid_phone":
            result_status = "permanent_error"
        return self._build_result(
            order_id,
            result_status,
            str(send_result.get("reason") or "Error en envio real."),
            expected_tickets=int(send_result.get("expected_tickets") or 0),
            found_tickets=int(send_result.get("found_tickets") or 0),
            phone_valid=bool(normalized_billing_phone),
            changed=True,
            payment_method=payment_method,
            masked_destination=str(send_result.get("masked_destination") or masked_destination),
            sent_tickets=int(send_result.get("sent_tickets") or 0),
        )

    @staticmethod
    def _safe_order_id(order: dict[str, Any]) -> int:
        try:
            return int(order.get("id") or 0)
        except (TypeError, ValueError, AttributeError):
            return 0

    @staticmethod
    def _normalize_argentine_phone(phone: Any) -> str | None:
        return normalize_argentine_phone(phone)

    @staticmethod
    def _build_waiting_payment_summary(reasons: set[str], order_status: str) -> str:
        if "payment_not_confirmed" in reasons:
            return "pago no confirmado"
        if "still_needs_payment" in reasons:
            return "todavia necesita pago"
        if "status_not_ready" in reasons:
            return f"estado {order_status}"
        return "en espera de pago"

    @staticmethod
    def _build_result(
        order_id: int,
        status: str,
        summary: str,
        expected_tickets: int = 0,
        found_tickets: int = 0,
        phone_valid: bool = False,
        changed: bool = True,
        **extra: Any,
    ) -> dict[str, Any]:
        return {
            "order_id": order_id,
            "status": status,
            "summary": summary,
            "expected_tickets": expected_tickets,
            "found_tickets": found_tickets,
            "phone_valid": phone_valid,
            "changed": changed,
            **extra,
        }

    @staticmethod
    def _did_result_change(
        previous_state: dict[str, Any] | None,
        status: str,
        expected_tickets: int,
        found_tickets: int,
        phone_valid: bool,
    ) -> bool:
        if not previous_state:
            return True

        return not (
            previous_state.get("status") == status
            and int(previous_state.get("expected_tickets") or 0) == expected_tickets
            and int(previous_state.get("found_tickets") or 0) == found_tickets
            and bool(previous_state.get("phone_normalized")) == phone_valid
        )

    @staticmethod
    def _build_summary(results: list[dict[str, Any]]) -> dict[str, int]:
        summary = {
            "analyzed": len(results),
            "simulated": 0,
            "sent": 0,
            "ignored": 0,
            "waiting": 0,
            "errors": 0,
            "already_sent": 0,
            "ready": 0,
        }
        for item in results:
            status = str(item.get("status") or "")
            if status in {"waiting_payment", "waiting_ticket"}:
                summary["waiting"] += 1
            elif status in {"retryable_error", "permanent_error"}:
                summary["errors"] += 1
            elif status in summary:
                summary[status] += 1
        return summary

    @staticmethod
    def _build_caption(ticket_pdf: dict[str, Any], index: int, total: int) -> str:
        lines = ["\U0001F39F\uFE0F Entrada Bacano"]
        event_name = str(ticket_pdf.get("event_name") or "").strip()
        ticket_type = str(ticket_pdf.get("ticket_type") or "").strip()

        if event_name:
            lines.append(f"Evento: {event_name}")
        if ticket_type:
            lines.append(f"Tipo: {ticket_type}")

        lines.append(f"Entrada {index} de {total}")
        return "\n".join(lines)

    @staticmethod
    def _build_customer_intro_message() -> str:
        return (
            "\U0001F39F\uFE0F \u00A1Tu compra en Bacano esta confirmada!\n\n"
            "Te enviamos tus entradas en PDF.\n"
            "Guardalas y presentalas desde tu telefono en el ingreso."
        )

    @staticmethod
    def _build_customer_intro_confirmation_message(
        ticket_pdfs: list[dict[str, Any]],
        expected_tickets: int,
    ) -> str:
        event_name = ""
        if ticket_pdfs:
            event_name = str(ticket_pdfs[0].get("event_name") or "").strip()
        event_line = event_name or "tu evento"
        return (
            f"¡Hola! 👋 Somos Bacano Club. Tenemos listas tus entradas para {event_line}.\n\n"
            f"Compraste {expected_tickets} entrada/s.\n\n"
            "¿Querés recibirlas por este WhatsApp? Respondé SI y te las enviamos acá."
        )

    @staticmethod
    def _build_customer_caption(ticket_pdf: dict[str, Any], index: int, total: int) -> str:
        lines = [f"Entrada {index} de {total}"]
        event_name = str(ticket_pdf.get("event_name") or "").strip()
        ticket_type = str(ticket_pdf.get("ticket_type") or "").strip()

        if event_name:
            lines.append(f"Evento: {event_name}")
        if ticket_type:
            lines.append(f"Tipo: {ticket_type}")

        return "\n".join(lines)

    @staticmethod
    def _send_pdf_to_bot(
        phone: str, pdf_path: Path, filename: str, caption: str
    ) -> tuple[bool, str]:
        payload = {
            "phone": phone,
            "file_path": str(pdf_path),
            "filename": filename,
            "caption": caption,
        }
        try:
            response = requests.post(
                ENDPOINT_URL,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException:
            return (
                False,
                "El bot principal debe estar encendido y escuchando en http://127.0.0.1:3000.",
            )

        try:
            data = response.json()
        except ValueError:
            return False, "El bot principal devolvio una respuesta no JSON."

        if response.ok and data.get("ok"):
            return True, "Documento enviado"

        return False, str(data.get("detail") or data.get("error") or "Error desconocido")

    @staticmethod
    def _send_text_to_bot(phone: str, text: str) -> tuple[bool, str]:
        payload = {
            "phone": phone,
            "text": text,
        }
        try:
            response = requests.post(
                "http://127.0.0.1:3000/internal/send-text",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException:
            return (
                False,
                "El bot principal debe estar encendido y escuchando en http://127.0.0.1:3000.",
            )

        try:
            data = response.json()
        except ValueError:
            return False, "El bot principal devolvio una respuesta no JSON."

        if response.ok and data.get("ok"):
            return True, "Texto enviado"
        return False, str(data.get("detail") or data.get("error") or "Error desconocido")

    @staticmethod
    def _is_affirmative_message(message: str) -> bool:
        normalized = (
            str(message or "")
            .strip()
            .lower()
            .replace("í", "i")
            .replace("ì", "i")
            .replace("ï", "i")
        )
        return normalized == "si"

    def _deliver_confirmed_order_to_customer(
        self,
        order_id: int,
        normalized_phone: str,
    ) -> dict[str, Any]:
        delivery_info = self._ticket_delivery_service.get_order_delivery_info(order_id)
        if self._delivery_state_service.has_been_sent(order_id):
            return {"ok": False, "order_id": order_id, "reason": "already_sent", "sent_tickets": 0}

        destination_dir = DEBUG_DIR / f"delivery_live_confirmed_{order_id}"
        prepare_result = self._ticket_delivery_service.prepare_order_tickets(order_id, destination_dir)
        if not prepare_result.get("ready"):
            return {
                "ok": False,
                "order_id": order_id,
                "reason": prepare_result.get("reason") or "Pedido no listo para enviar.",
                "sent_tickets": 0,
            }

        ticket_pdfs = prepare_result.get("ticket_pdfs") or []
        if not ticket_pdfs:
            return {"ok": False, "order_id": order_id, "reason": "No hay tickets PDF para enviar.", "sent_tickets": 0}

        self._delivery_state_service.mark_sending(
            order_id,
            payment_method=delivery_info.get("payment_method"),
            order_status=delivery_info.get("status"),
            expected_tickets=int(prepare_result.get("expected_tickets") or 0),
            found_tickets=int(prepare_result.get("found_tickets") or 0),
            phone_normalized=normalized_phone,
            metadata_json={"summary": "sending_live_confirmation"},
        )

        total = len(ticket_pdfs)
        sent_results: list[dict[str, Any]] = []
        for index, ticket_pdf in enumerate(ticket_pdfs, start=1):
            pdf_path = Path(ticket_pdf["pdf_path"])
            caption = self._build_customer_caption(ticket_pdf, index, total)
            if index == 1:
                caption = f"{self._build_customer_intro_message()}\n\n{caption}"
            ok, detail = self._send_pdf_to_bot(
                normalized_phone,
                pdf_path,
                pdf_path.name,
                caption,
            )
            sent_results.append({"index": index, "ok": ok, "detail": detail})
            if not ok:
                self._delivery_state_service.mark_retryable_error(
                    order_id,
                    payment_method=delivery_info.get("payment_method"),
                    order_status=delivery_info.get("status"),
                    expected_tickets=int(prepare_result.get("expected_tickets") or 0),
                    found_tickets=int(prepare_result.get("found_tickets") or 0),
                    sent_tickets=sum(1 for item in sent_results if item["ok"]),
                    phone_normalized=normalized_phone,
                    last_error=detail,
                    metadata_json={"summary": "document send failed after confirmation"},
                )
                return {
                    "ok": False,
                    "order_id": order_id,
                    "reason": detail,
                    "sent_tickets": sum(1 for item in sent_results if item["ok"]),
                }
            if index < total:
                time.sleep(1)

        current = self._delivery_state_service.get_order_state(order_id) or {}
        self._delivery_state_service.mark_sent(
            order_id,
            payment_method=delivery_info.get("payment_method"),
            order_status=delivery_info.get("status"),
            expected_tickets=int(prepare_result.get("expected_tickets") or 0),
            found_tickets=int(prepare_result.get("found_tickets") or 0),
            sent_tickets=total,
            phone_normalized=normalized_phone,
            attempt_count=int(current.get("attempt_count") or 0) + 1,
            customer_confirmed_at=DeliveryStateService._now_iso(),
            last_error=None,
            metadata_json={"summary": "live send after confirmation"},
        )
        return {"ok": True, "order_id": order_id, "sent_tickets": total}
