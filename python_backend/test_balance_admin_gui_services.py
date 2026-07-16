from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import config_manager
from run_balance_monitor import parse_args
from services.balance_admin_service import BalanceAdminService
from services.balance_monitor_service import BalanceMonitorService
from services.balance_settings_service import BalanceSettingsService


class FakeOrderService:
    def __init__(self) -> None:
        self.order = {
            "woocommerce_order_id": 39212,
            "client_id": 72,
            "dni_last4": "1234",
            "amount": "1000.00",
            "status": "paid",
            "created_at": "2026-07-15T12:00:00+00:00",
            "paid_at": "2026-07-15T12:39:32",
            "last_error": None,
        }

    def list_local_orders(self, *, limit=100, order_id=None):
        if order_id is not None and order_id != 39212:
            return []
        return [self.order]

    def get_local_order(self, order_id):
        return self.order if order_id == 39212 else None

    def get_local_load(self, reference):
        if reference != "WC-BALANCE-39212":
            return None
        return {
            "reference": reference,
            "status": "applied",
            "previous_balance": "32.056,00",
            "amount": "1.000,00",
            "new_balance": "33.056,00",
            "recarga_id": 66634,
            "historial_id": 339362,
            "last_error": None,
        }


class FakePaymentService:
    def get_client_by_id(self, client_id):
        return {"ok": True, "client_id": client_id, "name": "GOBEL, LUIS"}

    def check_order(self, order_id):
        return {
            "ok": True,
            "order_id": order_id,
            "woocommerce_status": "completed",
            "payment_method": "woo-mercado-pago-custom",
            "amount": "1000.00",
            "local_status": "credited",
            "paid": True,
            "credited": True,
            "can_credit": False,
            "date_paid": "2026-07-15T12:39:32",
            "reason": "Pago confirmado.",
        }


class FakeConfiguredSettings:
    def __init__(self, settings):
        self.settings = settings

    def get_settings(self):
        return self.settings


class NeverCalledWooCommerce:
    def get_orders(self, **_kwargs):
        raise AssertionError("No debe consultar WooCommerce con el monitor apagado.")


class BalanceSettingsTests(unittest.TestCase):
    def test_safe_defaults_and_persistence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite"
            service = BalanceSettingsService(db_path)
            defaults = service.get_settings()
            self.assertFalse(defaults["accept_new_loads"])
            self.assertFalse(defaults["monitor_payments"])
            self.assertFalse(defaults["auto_credit"])

            updated = service.update_settings(
                accept_new_loads=True,
                monitor_payments=True,
                auto_credit=True,
                monitor_after_order_id=39212,
                monitor_interval=60,
            )
            reloaded = BalanceSettingsService(db_path).get_settings()
            self.assertEqual(updated, reloaded)
            self.assertTrue(reloaded["auto_credit"])

    def test_auto_credit_requires_monitor_and_boundary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = BalanceSettingsService(Path(temp_dir) / "state.sqlite")
            with self.assertRaises(ValueError):
                service.update_settings(auto_credit=True)
            service.update_settings(monitor_payments=True)
            with self.assertRaises(ValueError):
                service.update_settings(auto_credit=True)

    def test_disabling_monitor_also_disables_auto_credit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = BalanceSettingsService(Path(temp_dir) / "state.sqlite")
            service.update_settings(
                monitor_payments=True,
                auto_credit=True,
                monitor_after_order_id=39212,
            )
            result = service.update_settings(monitor_payments=False)
            self.assertFalse(result["monitor_payments"])
            self.assertFalse(result["auto_credit"])

    def test_minimum_date_requires_timezone(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = BalanceSettingsService(Path(temp_dir) / "state.sqlite")
            with self.assertRaises(ValueError):
                service.update_settings(monitor_after_date="2026-07-16T10:00:00")
            result = service.update_settings(monitor_after_date="2026-07-16T10:00:00-03:00")
            self.assertEqual(result["monitor_after_date"], "2026-07-16T10:00:00-03:00")

    def test_disabled_configured_monitor_does_not_query_orders(self):
        settings = {
            "monitor_payments": False,
            "auto_credit": False,
            "monitor_after_order_id": 39212,
            "monitor_after_date": None,
        }
        service = BalanceMonitorService(
            woocommerce_client=NeverCalledWooCommerce(),
            credit_service=object(),
            order_service=object(),
            settings_service=FakeConfiguredSettings(settings),
        )
        result = service.scan_configured_orders()
        self.assertEqual(result["mode"], "disabled")
        self.assertEqual(result["summary"]["analyzed"], 0)

    def test_runner_settings_mode_is_explicit_and_does_not_accept_cli_boundary(self):
        args = parse_args(["--use-settings", "--once"])
        self.assertTrue(args.use_settings)
        self.assertFalse(args.live)
        with self.assertRaises(SystemExit):
            parse_args(["--use-settings", "--once", "--after-order-id", "39212"])


class BalanceAdminTests(unittest.TestCase):
    def setUp(self):
        self.service = BalanceAdminService(FakeOrderService(), FakePaymentService())

    def test_lists_recent_load_with_masked_dni_and_states(self):
        rows = self.service.list_recent_loads(refresh_remote=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["order_id"], 39212)
        self.assertEqual(rows[0]["client_name"], "GOBEL, LUIS")
        self.assertEqual(rows[0]["dni_masked"], "****1234")
        self.assertEqual(rows[0]["display_status"], "Acreditado")
        self.assertEqual(rows[0]["accreditation"], "Si")

    def test_load_detail_uses_existing_local_records(self):
        detail = self.service.get_load_detail(39212, refresh_remote=True)
        self.assertEqual(detail["reference"], "WC-BALANCE-39212")
        self.assertEqual(detail["previous_balance"], "32.056,00")
        self.assertEqual(detail["new_balance"], "33.056,00")
        self.assertEqual(detail["recarga_id"], 66634)
        self.assertEqual(detail["historial_id"], 339362)

    def test_display_states_are_clear(self):
        expected = {
            "awaiting_payment": "Pendiente",
            "paid": "Pagado",
            "credited": "Acreditado",
            "cancelled": "Cancelado",
            "failed": "Fallido",
            "error": "Error",
        }
        for raw, display in expected.items():
            self.assertEqual(self.service.display_status(raw), display)


class ConfigManagerTests(unittest.TestCase):
    def test_save_preserves_unedited_sections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            original = {
                "database": {"host": "old", "user": "root", "password": "secret", "database": "bacano"},
                "woocommerce": {"base_url": "https://example.test", "consumer_key": "key"},
                "admin_notifications": {"phone": "5490000000000"},
                "promotions": ["Promo anterior"],
            }
            config_path.write_text(json.dumps(original), encoding="utf-8")
            old_paths = config_manager.CONFIG_PATHS
            try:
                config_manager.CONFIG_PATHS = [str(config_path)]
                saved = config_manager.save_config(
                    {"database": {"host": "new"}, "promotions": ["Promo nueva"]}
                )
            finally:
                config_manager.CONFIG_PATHS = old_paths

            self.assertTrue(saved)
            result = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(result["database"]["host"], "new")
            self.assertEqual(result["database"]["password"], "secret")
            self.assertEqual(result["woocommerce"], original["woocommerce"])
            self.assertEqual(result["admin_notifications"], original["admin_notifications"])
            self.assertEqual(result["promotions"], ["Promo nueva"])


if __name__ == "__main__":
    unittest.main()
