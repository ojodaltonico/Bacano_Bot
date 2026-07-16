from __future__ import annotations

import unittest
import uuid
from pathlib import Path

from services.delivery_state_service import DeliveryStateService
from services.ticket_admin_service import TicketAdminService
from services.ticket_settings_service import TicketSettingsService
from utils.phone_utils import normalize_argentine_phone


def make_temp_db_path(prefix: str) -> Path:
    base_dir = Path(__file__).resolve().parent / "tmp_test_artifacts"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{prefix}_{uuid.uuid4().hex}.sqlite"


class FakeWooCommerceClient:
    def __init__(self, orders: dict[int, dict]) -> None:
        self.orders = orders

    def get_order(self, order_id: int):
        return self.orders[order_id]


class FakeTicketDeliveryService:
    def __init__(self, info: dict[int, dict], prepared: dict[int, dict]) -> None:
        self.info = info
        self.prepared = prepared

    def get_order_delivery_info(self, order_id: int):
        return self.info[order_id]

    def prepare_order_tickets(self, order_id: int, _destination_dir):
        return self.prepared[order_id]


class FakeOrderMonitorService:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def resend_order_to_phone(self, order_id: int, destination_phone: str):
        self.calls.append((order_id, destination_phone))
        return {
            "ok": True,
            "order_id": order_id,
            "normalized_destination": "5492939407879",
            "sent_tickets": 2,
        }


class TicketSettingsTests(unittest.TestCase):
    def test_safe_defaults_and_persistence(self):
        db_path = make_temp_db_path("ticket_settings")
        service = TicketSettingsService(db_path)
        defaults = service.get_settings()
        self.assertFalse(defaults["monitor_enabled"])
        self.assertTrue(defaults["test_mode"])
        self.assertFalse(defaults["auto_send_customer"])

        updated = service.update_settings(
            monitor_enabled=True,
            test_mode=True,
            test_phone="02923 40-7879",
            monitor_after_order_id=39213,
            monitor_interval=60,
        )
        reloaded = TicketSettingsService(db_path).get_settings()
        self.assertEqual(updated, reloaded)
        self.assertEqual(reloaded["test_phone"], "5492923407879")

    def test_auto_send_is_blocked_when_test_mode_is_on(self):
        db_path = make_temp_db_path("ticket_settings")
        service = TicketSettingsService(db_path)
        with self.assertRaises(ValueError):
            service.update_settings(
                monitor_enabled=True,
                test_mode=True,
                auto_send_customer=True,
            )

    def test_turning_test_mode_on_disables_auto_send(self):
        db_path = make_temp_db_path("ticket_settings")
        service = TicketSettingsService(db_path)
        service.update_settings(monitor_enabled=True, test_mode=False, auto_send_customer=True)
        result = service.update_settings(test_mode=True)
        self.assertFalse(result["auto_send_customer"])


class PhoneNormalizationTests(unittest.TestCase):
    def test_accepts_argentine_mobile_formats(self):
        cases = {
            "2923407879": "5492923407879",
            "02923407879": "5492923407879",
            "5492923407879": "5492923407879",
            "+54 9 2923 40 7879": "5492923407879",
            "(02923) 40-7879": "5492923407879",
            "02923-15-427103": "5492923427103",
        }
        for raw, expected in cases.items():
            self.assertEqual(normalize_argentine_phone(raw), expected)

    def test_rejects_invalid_or_ambiguous_values(self):
        self.assertIsNone(normalize_argentine_phone("15XXXXXXXX".replace("X", "1")))
        self.assertIsNone(normalize_argentine_phone(""))
        self.assertIsNone(normalize_argentine_phone("abc"))


class TicketAdminTests(unittest.TestCase):
    def test_lists_recent_deliveries_and_visible_statuses(self):
        db_path = make_temp_db_path("ticket_admin")
        state = DeliveryStateService(db_path)
        state.mark_sent(
            39216,
            payment_method="woo-mercado-pago-custom",
            order_status="processing",
            expected_tickets=4,
            found_tickets=4,
            sent_tickets=4,
            phone_normalized="5492939407879",
            order_date="2026-07-16T08:05:00-03:00",
            client_name="Sofia Telll",
            original_phone="2939407879",
            metadata_json={"summary": "manual test send"},
        )
        woo = FakeWooCommerceClient(
            {
                39216: {
                    "id": 39216,
                    "date_created": "2026-07-16T08:05:00-03:00",
                    "billing": {
                        "first_name": "Sofia",
                        "last_name": "Telll",
                        "phone": "2939407879",
                    },
                }
            }
        )
        ticket_delivery = FakeTicketDeliveryService(
            {39216: {"billing_phone": "2939407879", "expected_tickets": 4}},
            {39216: {"ready": True, "pdf_files": ["a.pdf"], "ticket_pdfs": [{"pdf_path": "a.pdf"}]}},
        )
        service = TicketAdminService(
            delivery_state_service=state,
            woocommerce_client=woo,
            ticket_delivery_service=ticket_delivery,
            order_monitor_service=FakeOrderMonitorService(),
        )

        rows = service.list_recent_deliveries()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["display_status"], "Enviado")
        self.assertEqual(rows[0]["original_phone"], "2939407879")
        self.assertEqual(rows[0]["normalized_phone"], "5492939407879")

    def test_ignored_are_hidden_by_default_and_visible_when_requested(self):
        db_path = make_temp_db_path("ticket_admin")
        state = DeliveryStateService(db_path)
        state.mark_ignored(39221, metadata_json={"summary": "efectivo/RRPP"})
        state.mark_sent(
            39216,
            payment_method="woo-mercado-pago-custom",
            order_status="processing",
            expected_tickets=4,
            found_tickets=4,
            sent_tickets=4,
            phone_normalized="5492939407879",
            order_date="2026-07-16T08:05:00-03:00",
            client_name="Sofia Telll",
            original_phone="2939407879",
        )
        woo = FakeWooCommerceClient(
            {
                39216: {"id": 39216, "date_created": "2026-07-16T08:05:00-03:00", "billing": {"first_name": "Sofia", "last_name": "Telll", "phone": "2939407879"}},
                39221: {"id": 39221, "date_created": "2026-07-16T08:06:00-03:00", "billing": {"first_name": "Caja", "last_name": "RRPP", "phone": ""}},
            }
        )
        ticket_delivery = FakeTicketDeliveryService(
            {
                39216: {"billing_phone": "2939407879", "expected_tickets": 4},
                39221: {"billing_phone": "", "expected_tickets": 0},
            },
            {
                39216: {"ready": True, "pdf_files": ["a.pdf"], "ticket_pdfs": [{"pdf_path": "a.pdf"}]},
                39221: {"ready": False, "pdf_files": [], "ticket_pdfs": []},
            },
        )
        service = TicketAdminService(
            delivery_state_service=state,
            woocommerce_client=woo,
            ticket_delivery_service=ticket_delivery,
            order_monitor_service=FakeOrderMonitorService(),
        )

        hidden = service.list_recent_deliveries()
        visible = service.list_recent_deliveries(show_ignored=True)

        self.assertEqual([row["order_id"] for row in hidden], [39216])
        self.assertEqual(sorted(row["order_id"] for row in visible), [39216, 39221])

    def test_operational_cutoff_filters_local_rows_without_woocommerce_calls(self):
        db_path = make_temp_db_path("ticket_admin_cutoff")
        state = DeliveryStateService(db_path)
        for order_id in (39216, 39237):
            state.mark_simulated(
                order_id,
                payment_method="woo-mercado-pago-custom",
                order_status="processing",
                expected_tickets=1,
                found_tickets=1,
                order_date="2026-07-16T12:00:00-03:00",
                client_name=f"Cliente {order_id}",
                original_phone="2923407879",
            )
        settings = TicketSettingsService(db_path)
        settings.update_settings(monitor_after_order_id=39225)
        woo = FakeWooCommerceClient({})
        service = TicketAdminService(
            delivery_state_service=state,
            woocommerce_client=woo,
            ticket_delivery_service=FakeTicketDeliveryService({}, {}),
            order_monitor_service=FakeOrderMonitorService(),
            ticket_settings_service=settings,
        )

        rows = service.list_recent_deliveries()

        self.assertEqual([row["order_id"] for row in rows], [39237])

    def test_manual_resend_goes_through_order_monitor_service(self):
        db_path = make_temp_db_path("ticket_admin")
        state = DeliveryStateService(db_path)
        monitor = FakeOrderMonitorService()
        service = TicketAdminService(
            delivery_state_service=state,
            woocommerce_client=FakeWooCommerceClient({}),
            ticket_delivery_service=FakeTicketDeliveryService({}, {}),
            order_monitor_service=monitor,
        )

        result = service.resend_tickets(39216, "02923 40-7879")

        self.assertTrue(result["ok"])
        self.assertEqual(monitor.calls, [(39216, "02923 40-7879")])


if __name__ == "__main__":
    unittest.main()
