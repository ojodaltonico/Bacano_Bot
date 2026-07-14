from __future__ import annotations

from pathlib import Path
import time
from typing import Any

import requests

from integrations.woocommerce_client import WooCommerceClient
from services.delivery_state_service import DeliveryStateService
from services.ticket_delivery_service import TicketDeliveryService
from utils.phone_utils import mask_phone, normalize_argentine_phone


DEBUG_DIR = Path(__file__).resolve().parent.parent / "debug"
ENDPOINT_URL = "http://127.0.0.1:3000/internal/send-document"
REQUEST_TIMEOUT = 30


class OrderMonitorService:
    def __init__(self) -> None:
        self._woocommerce_client = WooCommerceClient()
        self._ticket_delivery_service = TicketDeliveryService()
        self._delivery_state_service = DeliveryStateService()

    def scan_recent_orders(self, limit: int = 20, dry_run: bool = True) -> dict[str, Any]:
        orders = self._woocommerce_client.get_orders(per_page=limit, page=1)
        if not isinstance(orders, list):
            raise RuntimeError("WooCommerce no devolvio una lista de pedidos recientes.")

        results: list[dict[str, Any]] = []
        counts = {
            "analyzed": 0,
            "simulated": 0,
            "waiting": 0,
            "ignored": 0,
            "errors": 0,
            "already_sent": 0,
        }

        for order in orders[:limit]:
            counts["analyzed"] += 1
            try:
                result = self._scan_single_order(order, dry_run=dry_run)
            except Exception as exc:
                order_id = order.get("id") if isinstance(order, dict) else None
                order_id = int(order_id) if isinstance(order_id, int) else 0
                self._delivery_state_service.mark_error(
                    order_id,
                    last_error=str(exc),
                    metadata_json={"summary": "error_durante_analisis"},
                )
                result = {
                    "order_id": order_id,
                    "status": "error",
                    "summary": "error durante analisis",
                    "expected_tickets": 0,
                    "found_tickets": 0,
                    "phone_valid": False,
                }

            results.append(result)
            if result["status"] == "simulated":
                counts["simulated"] += 1
            elif result["status"] == "waiting":
                counts["waiting"] += 1
            elif result["status"] == "ignored":
                counts["ignored"] += 1
            elif result["status"] == "error":
                counts["errors"] += 1
            elif result["status"] == "already_sent":
                counts["already_sent"] += 1

        return {
            "results": results,
            "summary": counts,
        }

    def live_test_recent_orders(
        self, limit: int, test_phone: str, after_order_id: int
    ) -> dict[str, Any]:
        normalized_test_phone = self._normalize_argentine_phone(test_phone)
        if not normalized_test_phone:
            raise RuntimeError("El telefono de prueba no es valido.")

        orders = self._woocommerce_client.get_orders(per_page=limit, page=1)
        if not isinstance(orders, list):
            raise RuntimeError("WooCommerce no devolvio una lista de pedidos recientes.")

        results: list[dict[str, Any]] = []
        counts = {
            "analyzed": 0,
            "sent": 0,
            "ignored": 0,
            "waiting": 0,
            "errors": 0,
            "already_sent": 0,
            "skipped_before_cutoff": 0,
        }

        for order in orders[:limit]:
            order_id = int(order.get("id") or 0) if isinstance(order, dict) else 0
            if order_id <= after_order_id:
                counts["skipped_before_cutoff"] += 1
                continue

            counts["analyzed"] += 1
            try:
                result = self._live_test_single_order(order, normalized_test_phone)
            except Exception as exc:
                safe_error = str(exc) or "error durante analisis"
                self._delivery_state_service.mark_error(
                    order_id,
                    last_error=safe_error,
                    metadata_json={"summary": "error_durante_live_test"},
                )
                result = {
                    "order_id": order_id,
                    "status": "error",
                    "summary": safe_error,
                    "expected_tickets": 0,
                    "found_tickets": 0,
                    "changed": True,
                }

            results.append(result)
            status = result.get("status")
            if status == "sent":
                counts["sent"] += 1
            elif status == "ignored":
                counts["ignored"] += 1
            elif status == "waiting":
                counts["waiting"] += 1
            elif status == "already_sent":
                counts["already_sent"] += 1
            elif status == "error":
                counts["errors"] += 1

        return {
            "results": results,
            "summary": counts,
        }

    def live_recent_orders(self, limit: int, after_order_id: int) -> dict[str, Any]:
        orders = self._woocommerce_client.get_orders(per_page=limit, page=1)
        if not isinstance(orders, list):
            raise RuntimeError("WooCommerce no devolvio una lista de pedidos recientes.")

        results: list[dict[str, Any]] = []
        counts = {
            "analyzed": 0,
            "sent": 0,
            "ignored": 0,
            "waiting": 0,
            "errors": 0,
            "already_sent": 0,
            "skipped_before_cutoff": 0,
        }

        for order in orders[:limit]:
            order_id = int(order.get("id") or 0) if isinstance(order, dict) else 0
            if order_id <= after_order_id:
                counts["skipped_before_cutoff"] += 1
                continue

            counts["analyzed"] += 1
            try:
                result = self._live_single_order(order)
            except Exception as exc:
                safe_error = str(exc) or "error durante analisis"
                self._delivery_state_service.mark_error(
                    order_id,
                    last_error=safe_error,
                    metadata_json={"summary": "error_durante_live"},
                )
                result = {
                    "order_id": order_id,
                    "status": "error",
                    "summary": safe_error,
                    "expected_tickets": 0,
                    "found_tickets": 0,
                    "changed": True,
                    "payment_method": str(order.get("payment_method") or ""),
                    "masked_destination": "",
                    "sent_tickets": 0,
                }

            results.append(result)
            status = result.get("status")
            if status == "sent":
                counts["sent"] += 1
            elif status == "ignored":
                counts["ignored"] += 1
            elif status == "waiting":
                counts["waiting"] += 1
            elif status == "already_sent":
                counts["already_sent"] += 1
            elif status == "error":
                counts["errors"] += 1

        return {
            "results": results,
            "summary": counts,
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
            }

        ticket_pdfs = prepare_result.get("ticket_pdfs") or []
        if not ticket_pdfs:
            ticket_pdfs = [
                {
                    "transaction_id": "",
                    "ticket_type": "",
                    "event_name": "",
                    "pdf_path": pdf_path,
                }
                for pdf_path in (prepare_result.get("pdf_files") or [])
            ]

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
                self._delivery_state_service.mark_error(
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
                    "state_saved": "error",
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
            self._delivery_state_service.mark_error(
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
                "state_saved": "error",
            }

        destination_dir = DEBUG_DIR / f"delivery_live_{order_id}"
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
            }

        ticket_pdfs = prepare_result.get("ticket_pdfs") or []
        if not ticket_pdfs:
            ticket_pdfs = [
                {
                    "transaction_id": "",
                    "ticket_type": "",
                    "event_name": "",
                    "pdf_path": pdf_path,
                }
                for pdf_path in (prepare_result.get("pdf_files") or [])
            ]

        send_results: list[dict[str, Any]] = []
        total = len(ticket_pdfs)
        for index, ticket_pdf in enumerate(ticket_pdfs, start=1):
            pdf_path = Path(ticket_pdf["pdf_path"])
            caption = self._build_customer_caption(ticket_pdf, index, total)
            if index == 1:
                caption = f"{self._build_customer_intro_message()}\n\n{caption}"
            ok, detail = self._send_pdf_to_bot(
                normalized_billing_phone,
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
                self._delivery_state_service.mark_error(
                    order_id,
                    payment_method=delivery_info.get("payment_method"),
                    order_status=delivery_info.get("status"),
                    expected_tickets=int(prepare_result.get("expected_tickets") or 0),
                    found_tickets=int(prepare_result.get("found_tickets") or 0),
                    sent_tickets=sum(1 for item in send_results if item["ok"]),
                    phone_normalized=normalized_billing_phone,
                    last_error=detail,
                    metadata_json={"summary": "document send failed"},
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
                    "sent_tickets": sum(1 for item in send_results if item["ok"]),
                    "billing_phone_present": billing_phone_present,
                    "billing_phone_normalizable": True,
                    "masked_destination": masked_billing_phone,
                    "state_saved": "error",
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
            phone_normalized=normalized_billing_phone,
            attempt_count=previous_attempts + 1,
            last_error=None,
            metadata_json={"summary": "live send"},
        )
        return {
            "ok": True,
            "order_id": order_id,
            "already_sent": False,
            "status": delivery_info.get("status"),
            "payment_method": delivery_info.get("payment_method"),
            "expected_tickets": prepare_result.get("expected_tickets", 0),
            "found_tickets": prepare_result.get("found_tickets", 0),
            "sent_tickets": total,
            "billing_phone_present": billing_phone_present,
            "billing_phone_normalizable": True,
            "masked_destination": masked_billing_phone,
            "state_saved": "sent",
        }

    def _scan_single_order(self, order: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        order_id = int(order.get("id") or 0)
        payment_method = str(order.get("payment_method") or "")
        order_status = str(order.get("status") or "")
        previous_state = self._delivery_state_service.get_order_state(order_id)

        self._delivery_state_service.mark_detected(
            order_id,
            payment_method=payment_method,
            order_status=order_status,
        )

        if self._delivery_state_service.has_been_sent(order_id):
            return {
                "order_id": order_id,
                "status": "already_sent",
                "summary": "ya enviado",
                "expected_tickets": 0,
                "found_tickets": 0,
                "phone_valid": False,
                "changed": False,
            }

        if payment_method == "cod":
            self._delivery_state_service.mark_ignored(
                order_id,
                payment_method=payment_method,
                order_status=order_status,
                metadata_json={"summary": "efectivo/RRPP"},
            )
            return self._build_result(
                order_id,
                "ignored",
                "efectivo/RRPP",
                changed=self._did_result_change(previous_state, "ignored", 0, 0, False),
            )

        if payment_method != "woo-mercado-pago-custom":
            self._delivery_state_service.mark_ignored(
                order_id,
                payment_method=payment_method,
                order_status=order_status,
                metadata_json={"summary": "metodo no habilitado"},
            )
            return self._build_result(
                order_id,
                "ignored",
                "metodo no habilitado",
                changed=self._did_result_change(previous_state, "ignored", 0, 0, False),
            )

        if order_status in {"cancelled", "refunded", "failed"}:
            self._delivery_state_service.mark_ignored(
                order_id,
                payment_method=payment_method,
                order_status=order_status,
                metadata_json={"summary": f"estado {order_status}"},
            )
            return self._build_result(
                order_id,
                "ignored",
                f"estado {order_status}",
                changed=self._did_result_change(previous_state, "ignored", 0, 0, False),
            )

        delivery_info = self._ticket_delivery_service.get_order_delivery_info(order_id)
        normalized_phone = self._normalize_argentine_phone(delivery_info.get("billing_phone"))
        phone_valid = bool(normalized_phone)
        expected_tickets = int(delivery_info.get("expected_tickets") or 0)

        waiting_reasons = set(delivery_info.get("not_ready_reasons") or [])
        if {
            "payment_not_confirmed",
            "still_needs_payment",
            "status_not_ready",
            "missing_phone",
        } & waiting_reasons:
            summary = self._build_waiting_summary(waiting_reasons, order_status)
            self._delivery_state_service.mark_waiting(
                order_id,
                payment_method=payment_method,
                order_status=order_status,
                expected_tickets=int(delivery_info.get("expected_tickets") or 0),
                phone_normalized=normalized_phone,
                metadata_json={"summary": summary, "phone_valid": phone_valid},
            )
            return self._build_result(
                order_id,
                "waiting",
                summary,
                expected_tickets=expected_tickets,
                phone_valid=phone_valid,
                changed=self._did_result_change(
                    previous_state,
                    "waiting",
                    expected_tickets,
                    0,
                    phone_valid,
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
            summary = "tickets no generados todavia"
            if found_tickets and found_tickets < expected_tickets:
                summary = f"tickets {found_tickets}/{expected_tickets}"
            elif prepare_result.get("reason"):
                summary = str(prepare_result["reason"])

            self._delivery_state_service.mark_waiting(
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
                "waiting",
                summary,
                expected_tickets=expected_tickets,
                found_tickets=found_tickets,
                phone_valid=phone_valid,
                changed=self._did_result_change(
                    previous_state,
                    "waiting",
                    expected_tickets,
                    found_tickets,
                    phone_valid,
                ),
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
                    previous_state,
                    "simulated",
                    expected_tickets,
                    found_tickets,
                    phone_valid,
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
                previous_state,
                "ready",
                expected_tickets,
                found_tickets,
                phone_valid,
            ),
        )

    def _live_test_single_order(
        self, order: dict[str, Any], normalized_test_phone: str
    ) -> dict[str, Any]:
        dry_run_result = self._scan_single_order(order, dry_run=True)
        order_id = int(order.get("id") or 0)

        if dry_run_result["status"] == "already_sent":
            return {
                **dry_run_result,
                "changed": False,
            }

        if dry_run_result["status"] == "ignored":
            return dry_run_result

        if dry_run_result["status"] == "waiting":
            return dry_run_result

        if dry_run_result["status"] == "error":
            return dry_run_result

        send_result = self.send_order_for_test(order_id, normalized_test_phone, force=False)
        if send_result.get("already_sent"):
            return {
                "order_id": order_id,
                "status": "already_sent",
                "summary": "ya enviado",
                "expected_tickets": int(send_result.get("expected_tickets") or 0),
                "found_tickets": int(send_result.get("found_tickets") or 0),
                "phone_valid": True,
                "changed": False,
            }

        if send_result.get("ok"):
            return {
                "order_id": order_id,
                "status": "sent",
                "summary": "enviado a telefono de prueba",
                "expected_tickets": int(send_result.get("expected_tickets") or 0),
                "found_tickets": int(send_result.get("found_tickets") or 0),
                "phone_valid": True,
                "changed": True,
                "billing_phone_present": bool(send_result.get("billing_phone_present")),
                "billing_phone_normalizable": bool(send_result.get("billing_phone_normalizable")),
                "masked_real_destination": str(send_result.get("masked_real_destination") or ""),
            }

        return {
            "order_id": order_id,
            "status": "error",
            "summary": str(send_result.get("reason") or "Error en envio de prueba."),
            "expected_tickets": int(send_result.get("expected_tickets") or 0),
            "found_tickets": int(send_result.get("found_tickets") or 0),
            "phone_valid": True,
            "changed": True,
            "billing_phone_present": bool(send_result.get("billing_phone_present")),
            "billing_phone_normalizable": bool(send_result.get("billing_phone_normalizable")),
            "masked_real_destination": str(send_result.get("masked_real_destination") or ""),
        }

    def _live_single_order(self, order: dict[str, Any]) -> dict[str, Any]:
        dry_run_result = self._scan_single_order(order, dry_run=True)
        order_id = int(order.get("id") or 0)
        payment_method = str(order.get("payment_method") or "")
        delivery_info = self._ticket_delivery_service.get_order_delivery_info(order_id)
        normalized_billing_phone = self._normalize_argentine_phone(delivery_info.get("billing_phone"))
        masked_destination = mask_phone(normalized_billing_phone or delivery_info.get("billing_phone"))

        if dry_run_result["status"] == "already_sent":
            return {
                **dry_run_result,
                "payment_method": payment_method,
                "masked_destination": masked_destination,
                "sent_tickets": 0,
                "changed": False,
            }

        ready_candidate = (
            payment_method == "woo-mercado-pago-custom"
            and str(delivery_info.get("status") or "") in {"processing", "completed"}
            and bool(delivery_info.get("date_paid"))
            and not bool(delivery_info.get("needs_payment"))
        )
        if ready_candidate and not normalized_billing_phone:
            self._delivery_state_service.mark_error(
                order_id,
                payment_method=payment_method,
                order_status=delivery_info.get("status"),
                expected_tickets=int(delivery_info.get("expected_tickets") or 0),
                found_tickets=0,
                sent_tickets=0,
                phone_normalized=None,
                last_error="invalid_phone",
                metadata_json={"summary": "invalid_phone"},
            )
            return {
                "order_id": order_id,
                "status": "error",
                "summary": "invalid_phone",
                "expected_tickets": int(delivery_info.get("expected_tickets") or 0),
                "found_tickets": 0,
                "phone_valid": False,
                "changed": True,
                "payment_method": payment_method,
                "masked_destination": masked_destination,
                "sent_tickets": 0,
            }

        if dry_run_result["status"] in {"ignored", "waiting", "error"}:
            return {
                **dry_run_result,
                "payment_method": payment_method,
                "masked_destination": masked_destination,
                "sent_tickets": 0,
            }

        send_result = self.send_order_to_customer(order_id)
        if send_result.get("already_sent"):
            return {
                "order_id": order_id,
                "status": "already_sent",
                "summary": "ya enviado",
                "expected_tickets": int(send_result.get("expected_tickets") or 0),
                "found_tickets": int(send_result.get("found_tickets") or 0),
                "phone_valid": True,
                "changed": False,
                "payment_method": payment_method,
                "masked_destination": str(send_result.get("masked_destination") or masked_destination),
                "sent_tickets": 0,
            }

        if send_result.get("ok"):
            return {
                "order_id": order_id,
                "status": "sent",
                "summary": "enviado a telefono de facturacion",
                "expected_tickets": int(send_result.get("expected_tickets") or 0),
                "found_tickets": int(send_result.get("found_tickets") or 0),
                "phone_valid": True,
                "changed": True,
                "payment_method": payment_method,
                "masked_destination": str(send_result.get("masked_destination") or masked_destination),
                "sent_tickets": int(send_result.get("sent_tickets") or 0),
            }

        return {
            "order_id": order_id,
            "status": "error",
            "summary": str(send_result.get("reason") or "Error en envio real."),
            "expected_tickets": int(send_result.get("expected_tickets") or 0),
            "found_tickets": int(send_result.get("found_tickets") or 0),
            "phone_valid": bool(normalized_billing_phone),
            "changed": True,
            "payment_method": payment_method,
            "masked_destination": str(send_result.get("masked_destination") or masked_destination),
            "sent_tickets": int(send_result.get("sent_tickets") or 0),
        }

    @staticmethod
    def _normalize_argentine_phone(phone: Any) -> str | None:
        return normalize_argentine_phone(phone)

    @staticmethod
    def _build_waiting_summary(reasons: set[str], order_status: str) -> str:
        if "payment_not_confirmed" in reasons:
            return "pago no confirmado"
        if "still_needs_payment" in reasons:
            return "todavia necesita pago"
        if "status_not_ready" in reasons:
            return f"estado {order_status}"
        if "missing_phone" in reasons:
            return "telefono no normalizable"
        return "en espera"

    @staticmethod
    def _build_result(
        order_id: int,
        status: str,
        summary: str,
        expected_tickets: int = 0,
        found_tickets: int = 0,
        phone_valid: bool = False,
        changed: bool = True,
    ) -> dict[str, Any]:
        return {
            "order_id": order_id,
            "status": status,
            "summary": summary,
            "expected_tickets": expected_tickets,
            "found_tickets": found_tickets,
            "phone_valid": phone_valid,
            "changed": changed,
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
