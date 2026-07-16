from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.delivery_state_service import DB_PATH
from utils.phone_utils import normalize_argentine_phone


DEFAULT_MONITOR_INTERVAL = 60
MIN_MONITOR_INTERVAL = 30


class TicketSettingsService:
    def __init__(self, sqlite_db_path: Path | None = None) -> None:
        self._db_path = Path(sqlite_db_path) if sqlite_db_path else DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def get_settings(self) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM ticket_settings WHERE id = 1").fetchone()
        if not row:
            self._init_db()
            return self.get_settings()
        result = dict(row)
        for key in ("monitor_enabled", "test_mode", "auto_send_customer"):
            result[key] = bool(result[key])
        return result

    def update_settings(self, **changes: Any) -> dict[str, Any]:
        allowed = {
            "monitor_enabled",
            "test_mode",
            "auto_send_customer",
            "test_phone",
            "monitor_after_order_id",
            "monitor_after_date",
            "monitor_interval",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("Opciones desconocidas: " + ", ".join(sorted(unknown)))

        current = self.get_settings()
        merged = {**current, **changes}
        merged["monitor_enabled"] = bool(merged["monitor_enabled"])
        merged["test_mode"] = bool(merged["test_mode"])
        merged["auto_send_customer"] = bool(merged["auto_send_customer"])

        test_phone = str(merged.get("test_phone") or "").strip()
        if test_phone:
            normalized_test_phone = normalize_argentine_phone(test_phone)
            if not normalized_test_phone:
                raise ValueError("El telefono de prueba no es un celular argentino valido.")
            merged["test_phone"] = normalized_test_phone
        else:
            merged["test_phone"] = None

        after_order_id = merged.get("monitor_after_order_id")
        if after_order_id in ("", None):
            merged["monitor_after_order_id"] = None
        else:
            after_order_id = int(after_order_id)
            if after_order_id < 0:
                raise ValueError("El order_id minimo no puede ser negativo.")
            merged["monitor_after_order_id"] = after_order_id

        after_date = str(merged.get("monitor_after_date") or "").strip()
        merged["monitor_after_date"] = after_date or None
        if merged["monitor_after_date"]:
            parsed_date = datetime.fromisoformat(merged["monitor_after_date"].replace("Z", "+00:00"))
            if parsed_date.tzinfo is None:
                raise ValueError("La fecha minima debe incluir zona horaria.")
            merged["monitor_after_date"] = parsed_date.isoformat()

        interval = int(merged.get("monitor_interval") or DEFAULT_MONITOR_INTERVAL)
        if interval < MIN_MONITOR_INTERVAL:
            raise ValueError(f"El intervalo minimo es {MIN_MONITOR_INTERVAL} segundos.")
        merged["monitor_interval"] = interval

        if changes.get("auto_send_customer") and not merged["monitor_enabled"]:
            raise ValueError("No se puede activar el envio automatico con el monitor apagado.")
        if changes.get("auto_send_customer") and merged["test_mode"]:
            raise ValueError("No se puede activar el envio automatico mientras el modo prueba este activo.")

        if not merged["monitor_enabled"] or merged["test_mode"]:
            merged["auto_send_customer"] = False

        merged["updated_at"] = self._now_iso()

        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE ticket_settings
                SET monitor_enabled = ?, test_mode = ?, auto_send_customer = ?,
                    test_phone = ?, monitor_after_order_id = ?, monitor_after_date = ?,
                    monitor_interval = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    int(merged["monitor_enabled"]),
                    int(merged["test_mode"]),
                    int(merged["auto_send_customer"]),
                    merged["test_phone"],
                    merged["monitor_after_order_id"],
                    merged["monitor_after_date"],
                    merged["monitor_interval"],
                    merged["updated_at"],
                ),
            )
            conn.commit()
        return self.get_settings()

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    monitor_enabled INTEGER NOT NULL DEFAULT 0,
                    test_mode INTEGER NOT NULL DEFAULT 1,
                    auto_send_customer INTEGER NOT NULL DEFAULT 0,
                    test_phone TEXT,
                    monitor_after_order_id INTEGER,
                    monitor_after_date TEXT,
                    monitor_interval INTEGER NOT NULL DEFAULT 60,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO ticket_settings (
                    id, monitor_enabled, test_mode, auto_send_customer, test_phone,
                    monitor_after_order_id, monitor_after_date, monitor_interval, updated_at
                ) VALUES (1, 0, 1, 0, NULL, NULL, NULL, ?, ?)
                """,
                (DEFAULT_MONITOR_INTERVAL, self._now_iso()),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
