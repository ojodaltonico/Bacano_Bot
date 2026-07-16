from __future__ import annotations

from typing import Any


BALANCE_LOAD_OPERATION = "balance_load"


def meta_to_map(meta_data: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(meta_data, list):
        return result

    for item in meta_data:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key:
            result[key] = str(item.get("value") or "")
    return result


def analyze_tickera_evidence(
    order: dict[str, Any],
    meta: dict[str, str] | None = None,
) -> dict[str, Any]:
    meta = meta or meta_to_map(order.get("meta_data"))
    evidence: list[str] = []
    line_items_summary: list[dict[str, Any]] = []

    for item in order.get("line_items") or []:
        if not isinstance(item, dict):
            continue

        item_meta_keys: list[str] = []
        for meta_item in item.get("meta_data") or []:
            if not isinstance(meta_item, dict):
                continue
            key = str(meta_item.get("key") or "").strip()
            if key:
                item_meta_keys.append(key)

        line_items_summary.append(
            {
                "id": item.get("id"),
                "name": str(item.get("name") or "").strip(),
                "product_id": item.get("product_id"),
                "variation_id": item.get("variation_id"),
                "quantity": int(item.get("quantity") or 0),
                "meta_keys": item_meta_keys,
            }
        )

        for meta_key in item_meta_keys:
            lowered_key = meta_key.lower()
            if lowered_key.startswith("tc_"):
                evidence.append(f"line_item_meta:{meta_key}")
            elif lowered_key in {
                "ticket type",
                "event",
                "ticket instance",
                "ticket_instance",
                "download_ticket",
            }:
                evidence.append(f"line_item_meta:{meta_key}")
            elif "ticket_type" in lowered_key or "ticket_instance" in lowered_key:
                evidence.append(f"line_item_meta:{meta_key}")

    fee_lines_summary = [
        {
            "id": item.get("id"),
            "name": str(item.get("name") or "").strip(),
            "total": item.get("total"),
            "tax_status": item.get("tax_status"),
        }
        for item in (order.get("fee_lines") or [])
        if isinstance(item, dict)
    ]

    order_meta_keys_matching: list[str] = []
    for key in meta.keys():
        lowered_key = key.lower()
        if lowered_key.startswith("tc_") or "tickera" in lowered_key or "ticket" in lowered_key:
            order_meta_keys_matching.append(key)
            evidence.append(f"order_meta:{key}")

    return {
        "contains_tickera": bool(evidence),
        "evidence": sorted(set(evidence)),
        "line_items": line_items_summary,
        "fee_lines": fee_lines_summary,
        "order_meta_keys_matching": sorted(set(order_meta_keys_matching)),
    }


def evaluate_ticket_order(
    order: dict[str, Any],
    meta: dict[str, str] | None = None,
) -> dict[str, Any]:
    meta = meta or meta_to_map(order.get("meta_data"))
    operation_type = str(meta.get("_bacano_operation_type") or "").strip()
    expected_tickets = sum(
        int(item.get("quantity") or 0)
        for item in (order.get("line_items") or [])
        if isinstance(item, dict)
    )
    tickera_diagnostics = analyze_tickera_evidence(order, meta)
    has_tickera_evidence = bool(tickera_diagnostics.get("contains_tickera"))

    exclusion_reasons: list[str] = []
    if operation_type == BALANCE_LOAD_OPERATION:
        exclusion_reasons.append("balance_load_operation")
    if expected_tickets <= 0:
        exclusion_reasons.append("no_ticket_quantity")
    if not has_tickera_evidence:
        exclusion_reasons.append("missing_tickera_evidence")

    return {
        "operation_type": operation_type,
        "is_balance_load": operation_type == BALANCE_LOAD_OPERATION,
        "expected_tickets": expected_tickets,
        "has_tickera_evidence": has_tickera_evidence,
        "tickera_diagnostics": tickera_diagnostics,
        "is_ticket_order": not exclusion_reasons,
        "exclusion_reasons": exclusion_reasons,
    }
