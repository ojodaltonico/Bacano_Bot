from __future__ import annotations

import unittest

from services.balance_monitor_service import BalanceMonitorService
from run_balance_monitor import parse_args


def balance_order(order_id: int = 40000, payment_method: str = "woo-mercado-pago-custom") -> dict:
    return {
        "id": order_id,
        "payment_method": payment_method,
        "meta_data": [
            {"key": "_bacano_operation_type", "value": "balance_load"},
        ],
    }


class FakeWooCommerceClient:
    def __init__(self, orders: list[dict]) -> None:
        self.orders = orders

    def get_orders(self, **_kwargs):
        return self.orders


class FakePagedWooCommerceClient:
    def __init__(self, pages: dict[int, list[dict]]) -> None:
        self.pages = pages
        self.requested_pages: list[int] = []

    def get_orders(self, **kwargs):
        page = int(kwargs["page"])
        self.requested_pages.append(page)
        return self.pages.get(page, [])


class FakeCreditService:
    def __init__(self, preview: dict, applied: dict | None = None) -> None:
        self.preview = preview
        self.applied = applied or {"ok": True}
        self.preview_calls: list[int] = []
        self.apply_calls: list[tuple[int, int]] = []

    def preview_credit(self, order_id: int) -> dict:
        self.preview_calls.append(order_id)
        return self.preview

    def apply_credit(self, order_id: int, client_id: int) -> dict:
        self.apply_calls.append((order_id, client_id))
        return self.applied


class SelectiveCreditService(FakeCreditService):
    def preview_credit(self, order_id: int) -> dict:
        self.preview_calls.append(order_id)
        if order_id == 40000:
            raise RuntimeError("Fallo consultando https://privado.example/secret")
        return {
            "ok": False,
            "reason": "already_credited",
            "check": {"credited": True, "reference": f"WC-BALANCE-{order_id}"},
        }


class FakeOrderService:
    def __init__(self) -> None:
        self.updates: list[tuple[int, dict]] = []

    def get_local_order(self, _order_id: int):
        return {"status": "paid"}

    def update_local_order_status(self, order_id: int, **kwargs) -> None:
        self.updates.append((order_id, kwargs))


class BalanceMonitorServiceTests(unittest.TestCase):
    def make_service(self, orders: list[dict], credit: FakeCreditService):
        order_service = FakeOrderService()
        service = BalanceMonitorService(
            woocommerce_client=FakeWooCommerceClient(orders),
            credit_service=credit,
            order_service=order_service,
        )
        return service, order_service

    def test_ignores_non_balance_and_other_payment_methods(self):
        non_balance = {"id": 39999, "payment_method": "woo-mercado-pago-custom", "meta_data": []}
        credit = FakeCreditService({"ok": True})
        other_methods = [
            balance_order(40000 + index, payment_method=method)
            for index, method in enumerate(("cod", "bacs", "cheque", "otro"))
        ]
        service, _ = self.make_service([non_balance, *other_methods], credit)

        result = service.scan_recent_orders(after_order_id=39000)

        self.assertEqual(result["summary"]["ignored"], 4)
        self.assertEqual(credit.preview_calls, [])

    def test_tickera_evidence_is_never_applied(self):
        credit = FakeCreditService(
            {
                "ok": False,
                "message": "El pedido contiene evidencia concreta de Tickera.",
                "tickera_diagnostics": {"contains_tickera": True},
            }
        )
        service, _ = self.make_service([balance_order()], credit)

        result = service.scan_recent_orders(live=True, after_order_id=39999)

        self.assertEqual(result["results"][0]["status"], "error")
        self.assertEqual(credit.apply_calls, [])

    def test_dry_run_never_calls_apply(self):
        credit = FakeCreditService(
            {
                "ok": True,
                "order_id": 40000,
                "client_id": 72,
                "client_name": "Cliente",
                "amount": "1000.00",
                "reference": "WC-BALANCE-40000",
                "preview": {},
            }
        )
        service, _ = self.make_service([balance_order()], credit)

        result = service.scan_recent_orders(live=False, after_order_id=39999)

        self.assertEqual(result["results"][0]["status"], "would_credit")
        self.assertEqual(credit.apply_calls, [])

    def test_already_credited_is_ignored(self):
        credit = FakeCreditService(
            {
                "ok": False,
                "reason": "already_credited",
                "message": "El pedido ya fue acreditado.",
                "check": {"credited": True, "reference": "WC-BALANCE-40000"},
            }
        )
        service, _ = self.make_service([balance_order()], credit)

        result = service.scan_recent_orders(live=True, after_order_id=39999)

        self.assertEqual(result["results"][0]["status"], "ignored")
        self.assertEqual(credit.apply_calls, [])

    def test_live_delegates_to_existing_credit_service(self):
        credit = FakeCreditService(
            {"ok": True, "order_id": 40000, "client_id": 72},
            {
                "ok": True,
                "client_id": 72,
                "amount": "1.000,00",
                "reference": "WC-BALANCE-40000",
                "recarga_id": 1,
                "historial_id": 2,
                "verification": {"ok": True},
            },
        )
        service, _ = self.make_service([balance_order()], credit)

        result = service.scan_recent_orders(live=True, after_order_id=39999)

        self.assertEqual(result["results"][0]["status"], "credited")
        self.assertEqual(credit.apply_calls, [(40000, 72)])

    def test_inconsistency_records_local_error_and_prepares_alert(self):
        credit = FakeCreditService(
            {"ok": False, "reason": "cannot_credit", "message": "Metadata invalida."}
        )
        service, order_service = self.make_service([balance_order()], credit)

        result = service.scan_recent_orders(after_order_id=39999)

        self.assertEqual(result["results"][0]["status"], "error")
        self.assertTrue(result["results"][0]["admin_alert_required"])
        self.assertEqual(order_service.updates[0][1]["status"], "error")

    def test_paginates_until_reaching_order_id_boundary(self):
        client = FakePagedWooCommerceClient(
            {
                1: [balance_order(40002), balance_order(40001)],
                2: [balance_order(40000), balance_order(39999)],
            }
        )
        credit = FakeCreditService(
            {"ok": False, "reason": "already_credited", "check": {"credited": True}}
        )
        service = BalanceMonitorService(
            woocommerce_client=client,
            credit_service=credit,
            order_service=FakeOrderService(),
        )

        result = service.scan_recent_orders(limit=2, after_order_id=40000)

        self.assertEqual(client.requested_pages, [1, 2])
        self.assertEqual([item["order_id"] for item in result["results"]], [40001, 40002])

    def test_one_order_exception_does_not_stop_remaining_orders(self):
        credit = SelectiveCreditService({"ok": True})
        service, _ = self.make_service([balance_order(40001), balance_order(40000)], credit)

        result = service.scan_recent_orders(after_order_id=39999)

        self.assertEqual(result["summary"]["errors"], 1)
        self.assertEqual(result["summary"]["ignored"], 1)
        error = next(item for item in result["results"] if item["status"] == "error")
        self.assertEqual(error["order_id"], 40000)
        self.assertNotIn("https://", error["reason"])

    def test_failed_order_is_retried_on_next_scan(self):
        credit = SelectiveCreditService({"ok": True})
        service, _ = self.make_service([balance_order(40000)], credit)

        first = service.scan_recent_orders(after_order_id=39999)
        second = service.scan_recent_orders(after_order_id=39999)

        self.assertEqual(first["summary"]["errors"], 1)
        self.assertEqual(second["summary"]["errors"], 1)
        self.assertEqual(credit.preview_calls, [40000, 40000])

    def test_error_result_has_safe_administrative_fields(self):
        order = balance_order()
        order.update({"status": "completed", "total": "1000.00"})
        order["meta_data"].extend(
            [
                {"key": "_bacano_client_id", "value": "72"},
                {"key": "_bacano_balance_amount", "value": "1000.00"},
            ]
        )
        credit = FakeCreditService({"ok": False, "reason": "cannot_credit", "message": "Dato dudoso."})
        service, _ = self.make_service([order], credit)

        error = service.scan_recent_orders(after_order_id=39999)["results"][0]

        self.assertEqual(error["woocommerce_status"], "completed")
        self.assertEqual(error["payment_method"], "woo-mercado-pago-custom")
        self.assertEqual(error["client_id"], 72)
        self.assertEqual(error["amount"], "1000.00")
        self.assertNotIn("dni", str(error).lower())
        self.assertNotIn("email", str(error).lower())

    def test_inherited_admin_alert_removes_private_url(self):
        credit = FakeCreditService(
            {
                "ok": False,
                "message": "Error consultando WooCommerce.",
                "admin_alert_message": "Motivo: fallo en https://privado.example/order/40000",
            }
        )
        service, _ = self.make_service([balance_order()], credit)

        error = service.scan_recent_orders(after_order_id=39999)["results"][0]

        self.assertNotIn("https://", error["admin_alert_message"])
        self.assertIn("[URL OMITIDA]", error["admin_alert_message"])

    def test_cli_defaults_to_dry_run_and_live_requires_boundary(self):
        args = parse_args(["--once"])
        self.assertFalse(args.live)
        with self.assertRaises(SystemExit):
            parse_args(["--live", "--once"])


if __name__ == "__main__":
    unittest.main()
