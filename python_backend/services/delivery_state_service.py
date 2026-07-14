from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "bacano_bot.sqlite"
ALLOWED_STATES = {
    "detected",
    "ready",
    "simulated",
    "sent",
    "ignored",
    "waiting",
    "error",
}


class DeliveryStateService:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def get_order_state(self, order_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ticket_deliveries WHERE order_id = ?",
                (order_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def upsert_order_state(self, order_id: int, **fields: Any) -> dict[str, Any]:
        current = self.get_order_state(order_id)
        status = fields.get("status", current["status"] if current else None)
        if status and status not in ALLOWED_STATES:
            raise ValueError(f"Estado no permitido: {status}")

        if current and current["status"] == "sent" and status in {"ready", "simulated"}:
            return current

        now = self._now_iso()
        merged = {
            "status": current["status"] if current else "detected",
            "payment_method": current["payment_method"] if current else None,
            "order_status": current["order_status"] if current else None,
            "expected_tickets": current["expected_tickets"] if current else 0,
            "found_tickets": current["found_tickets"] if current else 0,
            "sent_tickets": current["sent_tickets"] if current else 0,
            "phone_normalized": current["phone_normalized"] if current else None,
            "last_error": current["last_error"] if current else None,
            "first_seen_at": current["first_seen_at"] if current else now,
            "updated_at": now,
            "sent_at": current["sent_at"] if current else None,
            "attempt_count": current["attempt_count"] if current else 0,
            "metadata_json": current["metadata_json"] if current else None,
        }
        merged.update(fields)

        if "metadata_json" in merged and merged["metadata_json"] is not None and not isinstance(
            merged["metadata_json"], str
        ):
            merged["metadata_json"] = json.dumps(merged["metadata_json"], ensure_ascii=False)

        if current and current["status"] == "sent" and current.get("sent_at"):
            merged["sent_at"] = current["sent_at"]

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ticket_deliveries (
                    order_id, status, payment_method, order_status, expected_tickets,
                    found_tickets, sent_tickets, phone_normalized, last_error,
                    first_seen_at, updated_at, sent_at, attempt_count, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    status = excluded.status,
                    payment_method = excluded.payment_method,
                    order_status = excluded.order_status,
                    expected_tickets = excluded.expected_tickets,
                    found_tickets = excluded.found_tickets,
                    sent_tickets = excluded.sent_tickets,
                    phone_normalized = excluded.phone_normalized,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at,
                    sent_at = CASE
                        WHEN ticket_deliveries.sent_at IS NOT NULL THEN ticket_deliveries.sent_at
                        ELSE excluded.sent_at
                    END,
                    attempt_count = excluded.attempt_count,
                    metadata_json = excluded.metadata_json
                """,
                (
                    order_id,
                    merged["status"],
                    merged["payment_method"],
                    merged["order_status"],
                    merged["expected_tickets"],
                    merged["found_tickets"],
                    merged["sent_tickets"],
                    merged["phone_normalized"],
                    merged["last_error"],
                    merged["first_seen_at"],
                    merged["updated_at"],
                    merged["sent_at"],
                    merged["attempt_count"],
                    merged["metadata_json"],
                ),
            )
            conn.commit()

        return self.get_order_state(order_id) or {}

    def mark_detected(self, order_id: int, **fields: Any) -> dict[str, Any]:
        return self.upsert_order_state(order_id, status="detected", **fields)

    def mark_simulated(self, order_id: int, **fields: Any) -> dict[str, Any]:
        return self.upsert_order_state(order_id, status="simulated", **fields)

    def mark_ignored(self, order_id: int, **fields: Any) -> dict[str, Any]:
        return self.upsert_order_state(order_id, status="ignored", **fields)

    def mark_waiting(self, order_id: int, **fields: Any) -> dict[str, Any]:
        return self.upsert_order_state(order_id, status="waiting", **fields)

    def mark_error(self, order_id: int, **fields: Any) -> dict[str, Any]:
        attempts = int(fields.pop("attempt_count", 0) or 0)
        current = self.get_order_state(order_id)
        if current:
            attempts = max(attempts, int(current.get("attempt_count") or 0) + 1)
        else:
            attempts = max(attempts, 1)
        return self.upsert_order_state(order_id, status="error", attempt_count=attempts, **fields)

    def mark_sent(self, order_id: int, **fields: Any) -> dict[str, Any]:
        current = self.get_order_state(order_id)
        sent_at = current["sent_at"] if current and current.get("sent_at") else self._now_iso()
        return self.upsert_order_state(order_id, status="sent", sent_at=sent_at, **fields)

    def mark_ready(self, order_id: int, **fields: Any) -> dict[str, Any]:
        return self.upsert_order_state(order_id, status="ready", **fields)

    def has_been_sent(self, order_id: int) -> bool:
        state = self.get_order_state(order_id)
        return bool(state and (state.get("status") == "sent" or state.get("sent_at")))

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ticket_deliveries ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    payment_method TEXT,
                    order_status TEXT,
                    expected_tickets INTEGER DEFAULT 0,
                    found_tickets INTEGER DEFAULT 0,
                    sent_tickets INTEGER DEFAULT 0,
                    phone_normalized TEXT,
                    last_error TEXT,
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sent_at TEXT,
                    attempt_count INTEGER DEFAULT 0,
                    metadata_json TEXT
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
