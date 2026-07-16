from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.delivery_state_service import DB_PATH


DEFAULT_MONITOR_INTERVAL = 60
MIN_MONITOR_INTERVAL = 30


class BalanceSettingsService:
    def __init__(self, sqlite_db_path: Path | None = None) -> None:
        self._db_path = Path(sqlite_db_path) if sqlite_db_path else DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def get_settings(self) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM balance_settings WHERE id = 1").fetchone()
        if not row:
            self._init_db()
            return self.get_settings()
        result = dict(row)
        for key in ("accept_new_loads", "monitor_payments", "auto_credit"):
            result[key] = bool(result[key])
        return result

    def update_settings(self, **changes: Any) -> dict[str, Any]:
        allowed = {
            "accept_new_loads",
            "monitor_payments",
            "auto_credit",
            "monitor_after_order_id",
            "monitor_after_date",
            "monitor_interval",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("Opciones desconocidas: " + ", ".join(sorted(unknown)))

        current = self.get_settings()
        merged = {**current, **changes}
        merged["accept_new_loads"] = bool(merged["accept_new_loads"])
        merged["monitor_payments"] = bool(merged["monitor_payments"])
        merged["auto_credit"] = bool(merged["auto_credit"])

        if changes.get("monitor_payments") is False:
            merged["auto_credit"] = False

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

        if changes.get("auto_credit") and not merged["monitor_payments"]:
            raise ValueError("No se puede activar credito automatico con el monitor apagado.")
        if merged["auto_credit"] and not (
            merged["monitor_after_order_id"] is not None or merged["monitor_after_date"]
        ):
            raise ValueError("El credito automatico requiere un order_id o fecha minima.")

        interval = int(merged.get("monitor_interval") or DEFAULT_MONITOR_INTERVAL)
        if interval < MIN_MONITOR_INTERVAL:
            raise ValueError(f"El intervalo minimo es {MIN_MONITOR_INTERVAL} segundos.")
        merged["monitor_interval"] = interval
        merged["updated_at"] = self._now_iso()

        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE balance_settings
                SET accept_new_loads = ?, monitor_payments = ?, auto_credit = ?,
                    monitor_after_order_id = ?, monitor_after_date = ?,
                    monitor_interval = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    int(merged["accept_new_loads"]),
                    int(merged["monitor_payments"]),
                    int(merged["auto_credit"]),
                    merged["monitor_after_order_id"],
                    merged["monitor_after_date"],
                    merged["monitor_interval"],
                    merged["updated_at"],
                ),
            )
            conn.commit()
        return self.get_settings()

    def can_accept_new_loads(self) -> bool:
        return bool(self.get_settings()["accept_new_loads"])

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS balance_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    accept_new_loads INTEGER NOT NULL DEFAULT 0,
                    monitor_payments INTEGER NOT NULL DEFAULT 0,
                    auto_credit INTEGER NOT NULL DEFAULT 0,
                    monitor_after_order_id INTEGER,
                    monitor_after_date TEXT,
                    monitor_interval INTEGER NOT NULL DEFAULT 60,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO balance_settings (
                    id, accept_new_loads, monitor_payments, auto_credit,
                    monitor_after_order_id, monitor_after_date,
                    monitor_interval, updated_at
                ) VALUES (1, 0, 0, 0, NULL, NULL, ?, ?)
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
