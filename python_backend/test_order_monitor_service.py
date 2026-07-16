from __future__ import annotations

import unittest

from services.order_monitor_service import OrderMonitorService


def ticket_order(
    order_id: int = 50000,
    *,
    quantity: int = 2,
    payment_method: str = "woo-mercado-pago-custom",
    status: str = "processing",
    date_paid: str | None = "2026-07-15T12:00:00",
    needs_payment: bool = False,
    include_tickera: bool = True,
    operation_type: str | None = None,
) -> dict:
    item_meta = []
    if include_tickera:
        item_meta = [
            {"key": "Ticket Type", "value": "General"},
            {"key": "Event", "value": "Bacano Fest"},
        ]
    meta_data = []
    if operation_type:
        meta_data.append({"key": "_bacano_operation_type", "value": operation_type})
    return {
        "id": order_id,
        "date_created": "2026-07-15T12:00:00-03:00",
        "billing": {
            "first_name": "Cliente",
            "last_name": str(order_id),
            "phone": "2923407879",
        },
        "payment_method": payment_method,
        "status": status,
        "date_paid": date_paid,
        "needs_payment": needs_payment,
        "meta_data": meta_data,
        "line_items": [
            {
                "id": order_id * 10,
                "name": "Entrada general",
                "product_id": 10,
                "variation_id": 0,
                "quantity": quantity,
                "meta_data": item_meta,
            }
        ],
    }


class FakeWooCommerceClient:
    def __init__(self, pages: dict[int, list[dict]]) -> None:
        self.pages = pages
        self.requested_pages: list[int] = []
        self.orders_by_id = {
            int(order["id"]): order
            for page in pages.values()
            for order in page
            if isinstance(order, dict) and order.get("id") is not None
        }

    def get_orders(self, **kwargs):
        page = int(kwargs.get("page", 1))
        self.requested_pages.append(page)
        return self.pages.get(page, [])

    def get_order(self, order_id: int):
        return self.orders_by_id[order_id]


class FakeTicketDeliveryService:
    def __init__(self, delivery_info: dict[int, dict] | None = None, prepare: dict[int, dict] | None = None) -> None:
        self.delivery_info = delivery_info or {}
        self.prepare = prepare or {}
        self.delivery_calls: list[int] = []
        self.prepare_calls: list[int] = []

    def get_order_delivery_info(self, order_id: int) -> dict:
        self.delivery_calls.append(order_id)
        return self.delivery_info[order_id]

    def prepare_order_tickets(self, order_id: int, _destination_dir) -> dict:
        self.prepare_calls.append(order_id)
        return self.prepare[order_id]


class FakeDeliveryStateService:
    def __init__(self) -> None:
        self.states: dict[int, dict] = {}
        self.calls: list[tuple[str, int, dict]] = []
        self.manual_resends: list[dict] = []

    def get_order_state(self, order_id: int):
        return self.states.get(order_id)

    def has_been_sent(self, order_id: int) -> bool:
        state = self.states.get(order_id)
        return bool(state and (state.get("status") == "sent" or state.get("sent_at")))

    def _set(self, name: str, order_id: int, status: str, **fields):
        current = self.states.get(order_id, {})
        updated = {**current, **fields, "status": status}
        self.states[order_id] = updated
        self.calls.append((name, order_id, fields))
        return updated

    def mark_detected(self, order_id: int, **fields):
        return self._set("mark_detected", order_id, "detected", **fields)

    def mark_simulated(self, order_id: int, **fields):
        return self._set("mark_simulated", order_id, "simulated", **fields)

    def mark_ignored(self, order_id: int, **fields):
        return self._set("mark_ignored", order_id, "ignored", **fields)

    def mark_waiting(self, order_id: int, **fields):
        return self._set("mark_waiting", order_id, "waiting", **fields)

    def mark_waiting_payment(self, order_id: int, **fields):
        return self._set("mark_waiting_payment", order_id, "waiting_payment", **fields)

    def mark_waiting_ticket(self, order_id: int, **fields):
        return self._set("mark_waiting_ticket", order_id, "waiting_ticket", **fields)

    def mark_ready(self, order_id: int, **fields):
        return self._set("mark_ready", order_id, "ready", **fields)

    def mark_sending(self, order_id: int, **fields):
        return self._set("mark_sending", order_id, "sending", **fields)

    def mark_retryable_error(self, order_id: int, **fields):
        current = self.states.get(order_id, {})
        attempts = int(current.get("attempt_count") or 0) + 1
        return self._set("mark_retryable_error", order_id, "retryable_error", attempt_count=attempts, **fields)

    def mark_permanent_error(self, order_id: int, **fields):
        current = self.states.get(order_id, {})
        attempts = int(current.get("attempt_count") or 0) + 1
        return self._set("mark_permanent_error", order_id, "permanent_error", attempt_count=attempts, **fields)

    def mark_error(self, order_id: int, **fields):
        return self.mark_retryable_error(order_id, **fields)

    def mark_sent(self, order_id: int, **fields):
        return self._set("mark_sent", order_id, "sent", sent_at="2026-07-15T12:00:00+00:00", **fields)

    def mark_awaiting_customer_confirmation(self, order_id: int, **fields):
        return self._set(
            "mark_awaiting_customer_confirmation",
            order_id,
            "awaiting_customer_confirmation",
            customer_prompted_at="2026-07-16T10:00:00+00:00",
            **fields,
        )

    def record_manual_resend(self, order_id: int, **fields):
        payload = {"order_id": order_id, **fields}
        self.manual_resends.append(payload)
        return payload

    def list_manual_resends(self, order_id: int, limit: int = 20):
        rows = [row for row in self.manual_resends if row["order_id"] == order_id]
        return rows[:limit]

    def list_pending_customer_confirmations(self, normalized_phone: str):
        return [
            {"order_id": order_id, **state}
            for order_id, state in self.states.items()
            if state.get("status") == "awaiting_customer_confirmation"
            and state.get("phone_normalized") == normalized_phone
        ]


class OrderMonitorServiceTests(unittest.TestCase):
    def make_service(
        self,
        *,
        pages: dict[int, list[dict]],
        delivery_info: dict[int, dict] | None = None,
        prepare: dict[int, dict] | None = None,
        state_service: FakeDeliveryStateService | None = None,
    ) -> tuple[OrderMonitorService, FakeWooCommerceClient, FakeTicketDeliveryService, FakeDeliveryStateService]:
        woo = FakeWooCommerceClient(pages)
        delivery = FakeTicketDeliveryService(delivery_info=delivery_info, prepare=prepare)
        state = state_service or FakeDeliveryStateService()
        service = OrderMonitorService(
            woocommerce_client=woo,
            ticket_delivery_service=delivery,
            delivery_state_service=state,
        )
        return service, woo, delivery, state

    def test_excludes_balance_load_orders(self):
        order = ticket_order(operation_type="balance_load")
        service, _, delivery, state = self.make_service(pages={1: [order]})

        result = service.scan_recent_orders(limit=20, dry_run=True)

        self.assertEqual(result["results"][0]["status"], "ignored")
        self.assertEqual(result["results"][0]["summary"], "pedido de carga de saldo")
        self.assertEqual(delivery.delivery_calls, [])
        self.assertEqual(state.states[50000]["status"], "ignored")

    def test_excludes_normal_woocommerce_order_without_tickera(self):
        order = ticket_order(include_tickera=False)
        service, _, delivery, _ = self.make_service(pages={1: [order]})

        result = service.scan_recent_orders(limit=20, dry_run=True)

        self.assertEqual(result["results"][0]["status"], "ignored")
        self.assertIn("Tickera", result["results"][0]["summary"])
        self.assertEqual(delivery.delivery_calls, [])

    def test_detects_valid_tickera_order(self):
        order = ticket_order()
        delivery_info = {
            50000: {
                "billing_phone": "5491111111111",
                "expected_tickets": 2,
                "not_ready_reasons": [],
                "status": "processing",
                "payment_method": "woo-mercado-pago-custom",
            }
        }
        prepare = {
            50000: {
                "ready": True,
                "expected_tickets": 2,
                "found_tickets": 2,
            }
        }
        service, _, _, state = self.make_service(
            pages={1: [order]},
            delivery_info=delivery_info,
            prepare=prepare,
        )

        result = service.scan_recent_orders(limit=20, dry_run=True)

        self.assertEqual(result["results"][0]["status"], "simulated")
        self.assertEqual(state.states[50000]["status"], "simulated")

    def test_zero_tickets_is_not_marked_as_sent(self):
        order = ticket_order(quantity=0)
        service, _, _, state = self.make_service(pages={1: [order]})

        result = service.scan_recent_orders(limit=20, dry_run=True)

        self.assertEqual(result["results"][0]["status"], "ignored")
        self.assertNotEqual(state.states[50000]["status"], "sent")

    def test_already_sent_order_does_not_return_to_detected(self):
        order = ticket_order()
        state = FakeDeliveryStateService()
        state.states[50000] = {"status": "sent", "sent_at": "2026-07-15T12:00:00+00:00"}
        service, _, delivery, state = self.make_service(pages={1: [order]}, state_service=state)

        result = service.scan_recent_orders(limit=20, dry_run=True)

        self.assertEqual(result["results"][0]["status"], "already_sent")
        self.assertEqual(delivery.delivery_calls, [])
        self.assertFalse(any(call[0] == "mark_detected" for call in state.calls))

    def test_paginates_multiple_pages_and_deduplicates(self):
        orders_page_1 = [ticket_order(50003), ticket_order(50002)]
        orders_page_2 = [ticket_order(50002), ticket_order(50001)]
        service, woo, _, _ = self.make_service(pages={1: orders_page_1, 2: orders_page_2})

        result = service.live_test_recent_orders(limit=2, test_phone="5491111111111", after_order_id=50000)

        self.assertEqual(woo.requested_pages[:2], [1, 2])
        self.assertGreaterEqual(len(woo.requested_pages), 2)
        self.assertEqual(sorted(item["order_id"] for item in result["results"]), [50001, 50002, 50003])

    def test_dry_run_never_processes_orders_at_or_before_cutoff(self):
        recent = ticket_order(50003)
        old = ticket_order(50000)
        delivery_info = {
            50003: {
                "billing_phone": "5491111111111",
                "expected_tickets": 2,
                "not_ready_reasons": [],
            }
        }
        prepare = {50003: {"ready": True, "found_tickets": 2}}
        service, _, delivery, state = self.make_service(
            pages={1: [recent, old]},
            delivery_info=delivery_info,
            prepare=prepare,
        )

        result = service.scan_recent_orders(
            limit=20,
            dry_run=True,
            after_order_id=50000,
        )

        self.assertEqual([item["order_id"] for item in result["results"]], [50003])
        self.assertNotIn(50000, state.states)
        self.assertEqual(delivery.prepare_calls, [50003])

    def test_retryable_error_is_retried_on_next_cycle(self):
        order = ticket_order()
        delivery_info = {
            50000: {
                "billing_phone": "5491111111111",
                "expected_tickets": 2,
                "not_ready_reasons": [],
                "status": "processing",
                "payment_method": "woo-mercado-pago-custom",
            }
        }
        prepare = {
            50000: {
                "ready": False,
                "reason": "Error iniciando sesion en WordPress",
                "not_ready_reasons": ["ticket_access_error"],
                "found_tickets": 0,
            }
        }
        service, _, delivery, state = self.make_service(
            pages={1: [order]},
            delivery_info=delivery_info,
            prepare=prepare,
        )

        first = service.scan_recent_orders(limit=20, dry_run=True)
        second = service.scan_recent_orders(limit=20, dry_run=True)

        self.assertEqual(first["results"][0]["status"], "retryable_error")
        self.assertEqual(second["results"][0]["status"], "retryable_error")
        self.assertEqual(delivery.prepare_calls, [50000, 50000])
        self.assertEqual(state.states[50000]["attempt_count"], 2)

    def test_ticket_not_generated_stays_waiting_ticket(self):
        order = ticket_order()
        delivery_info = {
            50000: {
                "billing_phone": "5491111111111",
                "expected_tickets": 2,
                "not_ready_reasons": [],
                "status": "processing",
                "payment_method": "woo-mercado-pago-custom",
            }
        }
        prepare = {
            50000: {
                "ready": False,
                "reason": "Tickera todavia no genero tickets descargables para el pedido.",
                "not_ready_reasons": ["ticket_not_generated"],
                "found_tickets": 0,
            }
        }
        service, _, _, state = self.make_service(
            pages={1: [order]},
            delivery_info=delivery_info,
            prepare=prepare,
        )

        result = service.scan_recent_orders(limit=20, dry_run=True)

        self.assertEqual(result["results"][0]["status"], "waiting_ticket")
        self.assertEqual(state.states[50000]["status"], "waiting_ticket")

    def test_idempotent_dry_run_reports_no_changes_when_already_simulated(self):
        order = ticket_order()
        delivery_info = {
            50000: {
                "billing_phone": "5491111111111",
                "expected_tickets": 2,
                "not_ready_reasons": [],
                "status": "processing",
                "payment_method": "woo-mercado-pago-custom",
            }
        }
        prepare = {
            50000: {
                "ready": True,
                "expected_tickets": 2,
                "found_tickets": 2,
            }
        }
        state = FakeDeliveryStateService()
        state.states[50000] = {
            "status": "simulated",
            "payment_method": "woo-mercado-pago-custom",
            "order_status": "processing",
            "expected_tickets": 2,
            "found_tickets": 2,
            "phone_normalized": "5491111111111",
        }
        service, _, _, _ = self.make_service(
            pages={1: [order]},
            delivery_info=delivery_info,
            prepare=prepare,
            state_service=state,
        )

        result = service.scan_recent_orders(limit=20, dry_run=True)

        self.assertEqual(result["results"][0]["status"], "simulated")
        self.assertFalse(result["results"][0]["changed"])
        self.assertEqual(state.states[50000]["status"], "simulated")

    def test_failed_order_can_be_re_evaluated_later(self):
        order = ticket_order()
        delivery_info = {
            50000: {
                "billing_phone": "5491111111111",
                "expected_tickets": 2,
                "not_ready_reasons": [],
                "status": "processing",
                "payment_method": "woo-mercado-pago-custom",
            }
        }
        prepare = {
            50000: {
                "ready": False,
                "reason": "Error descargando un ticket PDF: timeout",
                "not_ready_reasons": ["ticket_access_error"],
                "found_tickets": 0,
            }
        }
        service, _, delivery, _ = self.make_service(
            pages={1: [order]},
            delivery_info=delivery_info,
            prepare=prepare,
        )

        service.scan_recent_orders(limit=20, dry_run=True)
        service.scan_recent_orders(limit=20, dry_run=True)

        self.assertEqual(delivery.prepare_calls, [50000, 50000])

    def test_configured_mode_respects_test_priority(self):
        order = ticket_order()
        delivery_info = {
            50000: {
                "billing_phone": "2939407879",
                "expected_tickets": 2,
                "not_ready_reasons": [],
                "status": "processing",
                "payment_method": "woo-mercado-pago-custom",
            }
        }
        prepare = {
            50000: {
                "ready": True,
                "expected_tickets": 2,
                "found_tickets": 2,
                "ticket_pdfs": [],
            }
        }
        service, _, _, _ = self.make_service(
            pages={1: [order]},
            delivery_info=delivery_info,
            prepare=prepare,
        )

        class Settings:
            def get_settings(self_inner):
                return {
                    "monitor_enabled": True,
                    "test_mode": True,
                    "auto_send_customer": True,
                    "test_phone": "5491111111111",
                    "monitor_after_order_id": 49999,
                    "monitor_after_date": None,
                }

        service._settings_service = Settings()
        service.send_order_for_test = lambda order_id, test_phone, force=False: {
            "ok": True,
            "order_id": order_id,
            "expected_tickets": 2,
            "found_tickets": 2,
            "sent_tickets": 2,
            "billing_phone_present": True,
            "billing_phone_normalizable": True,
            "masked_real_destination": "********7879",
        }
        service.send_order_to_customer = lambda order_id: {"ok": False, "reason": "should_not_happen"}

        result = service.scan_configured_orders(limit=20)

        self.assertEqual(result["mode"], "live-test")
        self.assertEqual(result["summary"]["sent"], 1)

    def test_configured_mode_off_does_not_query_orders(self):
        service, woo, _, _ = self.make_service(pages={})

        class Settings:
            def get_settings(self_inner):
                return {
                    "monitor_enabled": False,
                    "test_mode": True,
                    "auto_send_customer": False,
                    "test_phone": None,
                    "monitor_after_order_id": None,
                    "monitor_after_date": None,
                }

        service._settings_service = Settings()
        result = service.scan_configured_orders(limit=20)
        self.assertEqual(result["mode"], "disabled")
        self.assertEqual(woo.requested_pages, [])

    def test_manual_resend_does_not_alter_original_sent_state(self):
        order = ticket_order()
        delivery_info = {
            50000: {
                "billing_phone": "2939407879",
                "expected_tickets": 2,
                "status": "processing",
                "payment_method": "woo-mercado-pago-custom",
            }
        }
        prepare = {
            50000: {
                "ready": True,
                "expected_tickets": 2,
                "found_tickets": 2,
                "ticket_pdfs": [
                    {"pdf_path": "C:/tmp/ticket-1.pdf", "event_name": "Bacano", "ticket_type": "General"},
                    {"pdf_path": "C:/tmp/ticket-2.pdf", "event_name": "Bacano", "ticket_type": "General"},
                ],
            }
        }
        state = FakeDeliveryStateService()
        state.states[50000] = {
            "status": "sent",
            "sent_at": "2026-07-16T11:05:41+00:00",
            "expected_tickets": 2,
            "found_tickets": 2,
            "sent_tickets": 2,
            "phone_normalized": "5492939407879",
        }
        service, _, _, _ = self.make_service(
            pages={1: [order]},
            delivery_info=delivery_info,
            prepare=prepare,
            state_service=state,
        )

        original_sender = OrderMonitorService._send_pdf_to_bot
        OrderMonitorService._send_pdf_to_bot = staticmethod(lambda *_args: (True, "Documento enviado"))
        try:
            result = service.resend_order_to_phone(50000, "02923 40-7879")
        finally:
            OrderMonitorService._send_pdf_to_bot = original_sender

        self.assertTrue(result["ok"])
        self.assertEqual(state.states[50000]["status"], "sent")
        self.assertEqual(state.states[50000]["sent_at"], "2026-07-16T11:05:41+00:00")
        self.assertEqual(len(state.manual_resends), 1)
        self.assertEqual(state.manual_resends[0]["normalized_phone"], "5492923407879")

    def test_live_message_initial_is_sent_once_without_pdfs(self):
        order = ticket_order()
        delivery_info = {
            50000: {
                "billing_phone": "2939407879",
                "expected_tickets": 2,
                "status": "processing",
                "payment_method": "woo-mercado-pago-custom",
                "not_ready_reasons": [],
            }
        }
        prepare = {
            50000: {
                "ready": True,
                "expected_tickets": 2,
                "found_tickets": 2,
                "ticket_pdfs": [
                    {"pdf_path": "C:/tmp/ticket-1.pdf", "event_name": "Bacano Fest", "ticket_type": "General"}
                ],
            }
        }
        service, _, _, state = self.make_service(
            pages={1: [order]},
            delivery_info=delivery_info,
            prepare=prepare,
        )
        sent_texts = []
        sent_pdfs = []
        original_text = OrderMonitorService._send_text_to_bot
        original_pdf = OrderMonitorService._send_pdf_to_bot
        OrderMonitorService._send_text_to_bot = staticmethod(lambda phone, text: (sent_texts.append((phone, text)) or True, "Texto enviado"))
        OrderMonitorService._send_pdf_to_bot = staticmethod(lambda *args: (sent_pdfs.append(args) or True, "Documento enviado"))
        try:
            first = service.live_recent_orders(limit=20, after_order_id=49999)
            second = service.live_recent_orders(limit=20, after_order_id=49999)
        finally:
            OrderMonitorService._send_text_to_bot = original_text
            OrderMonitorService._send_pdf_to_bot = original_pdf

        self.assertEqual(first["results"][0]["status"], "awaiting_customer_confirmation")
        self.assertEqual(second["results"][0]["status"], "awaiting_customer_confirmation")
        self.assertEqual(len(sent_texts), 1)
        self.assertEqual(len(sent_pdfs), 0)
        self.assertEqual(state.states[50000]["status"], "awaiting_customer_confirmation")

    def test_unregistered_whatsapp_number_is_permanent_and_not_retried(self):
        order = ticket_order()
        delivery_info = {
            50000: {
                "billing_phone": "2939407879",
                "expected_tickets": 2,
                "status": "processing",
                "payment_method": "woo-mercado-pago-custom",
                "not_ready_reasons": [],
            }
        }
        prepare = {
            50000: {
                "ready": True,
                "expected_tickets": 2,
                "found_tickets": 2,
                "ticket_pdfs": [
                    {"pdf_path": "C:/tmp/ticket-1.pdf", "event_name": "Bacano Fest", "ticket_type": "General"}
                ],
            }
        }
        service, _, _, state = self.make_service(
            pages={1: [order]},
            delivery_info=delivery_info,
            prepare=prepare,
        )
        send_attempts = []
        original_text = OrderMonitorService._send_text_to_bot
        OrderMonitorService._send_text_to_bot = staticmethod(
            lambda phone, text: (send_attempts.append((phone, text)) and True, "Numero no registrado en WhatsApp")
        )
        try:
            first = service.live_recent_orders(limit=20, after_order_id=49999)
            second = service.live_recent_orders(limit=20, after_order_id=49999)
        finally:
            OrderMonitorService._send_text_to_bot = original_text

        self.assertEqual(first["results"][0]["status"], "permanent_error")
        self.assertEqual(second["results"][0]["status"], "permanent_error")
        self.assertFalse(second["results"][0]["changed"])
        self.assertEqual(state.states[50000]["status"], "permanent_error")
        self.assertEqual(len(send_attempts), 1)

    def test_affirmative_si_triggers_pending_delivery(self):
        order = ticket_order()
        delivery_info = {
            50000: {
                "billing_phone": "2939407879",
                "expected_tickets": 2,
                "status": "processing",
                "payment_method": "woo-mercado-pago-custom",
                "not_ready_reasons": [],
            }
        }
        prepare = {
            50000: {
                "ready": True,
                "expected_tickets": 2,
                "found_tickets": 2,
                "ticket_pdfs": [
                    {"pdf_path": "C:/tmp/ticket-1.pdf", "event_name": "Bacano Fest", "ticket_type": "General"},
                    {"pdf_path": "C:/tmp/ticket-2.pdf", "event_name": "Bacano Fest", "ticket_type": "General"},
                ],
            }
        }
        state = FakeDeliveryStateService()
        state.states[50000] = {
            "status": "awaiting_customer_confirmation",
            "phone_normalized": "5492939407879",
            "expected_tickets": 2,
            "found_tickets": 2,
        }
        service, _, _, state = self.make_service(
            pages={1: [order]},
            delivery_info=delivery_info,
            prepare=prepare,
            state_service=state,
        )
        sent_pdfs = []
        original_pdf = OrderMonitorService._send_pdf_to_bot
        OrderMonitorService._send_pdf_to_bot = staticmethod(lambda *args: (sent_pdfs.append(args) or True, "Documento enviado"))
        try:
            result = service.confirm_pending_customer_deliveries("5492939407879", "SI")
        finally:
            OrderMonitorService._send_pdf_to_bot = original_pdf

        self.assertTrue(result["handled"])
        self.assertEqual(state.states[50000]["status"], "sent")
        self.assertEqual(len(sent_pdfs), 2)

    def test_non_affirmative_message_does_not_trigger_delivery(self):
        service, _, _, _ = self.make_service(pages={})
        result = service.confirm_pending_customer_deliveries("5492939407879", "tal vez")
        self.assertFalse(result["handled"])

    def test_affirmative_si_with_accent_is_accepted(self):
        self.assertTrue(OrderMonitorService._is_affirmative_message("SÍ"))
        self.assertTrue(OrderMonitorService._is_affirmative_message(" sí "))


if __name__ == "__main__":
    unittest.main()
