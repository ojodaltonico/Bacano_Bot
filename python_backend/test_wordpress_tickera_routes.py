from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests.auth import HTTPBasicAuth

from config_manager import load_config


DEBUG_DIR = Path(__file__).resolve().parent / "debug"
OUTPUT_FILE = DEBUG_DIR / "wordpress_tickera_routes_sample.json"
REQUEST_TIMEOUT = 30
ROUTE_KEYWORDS = ("tickera", "ticket", "tc_", "tickets_instances", "tc-api")
PROBE_ROUTES = (
    "/wp-json/wp/v2/tc_tickets_instances",
    "/wp-json/wp/v2/tc_tickets_instance",
    "/wp-json/wp/v2/tickets",
    "/wp-json/tickera",
    "/wp-json/tc",
)
SENSITIVE_KEYWORDS = (
    "name",
    "first_name",
    "last_name",
    "email",
    "phone",
    "address",
    "password",
    "secret",
    "token",
    "nonce",
    "order_key",
    "payment_url",
    "user_agent",
    "ip",
)


class WordPressConfigError(RuntimeError):
    """Raised when WordPress configuration is missing or invalid."""


def load_wordpress_config() -> tuple[str, HTTPBasicAuth]:
    config = load_config()
    wordpress_config = config.get("wordpress")
    if not isinstance(wordpress_config, dict):
        raise WordPressConfigError("Falta la seccion 'wordpress' en la configuracion.")

    base_url = str(wordpress_config.get("base_url", "")).strip().rstrip("/")
    username = str(wordpress_config.get("username", "")).strip()
    app_password = str(wordpress_config.get("app_password", "")).strip()

    missing_fields = [
        field
        for field, value in (
            ("base_url", base_url),
            ("username", username),
            ("app_password", app_password),
        )
        if not value
    ]
    if missing_fields:
        raise WordPressConfigError(
            "Faltan campos requeridos en 'wordpress': " + ", ".join(missing_fields)
        )

    return base_url, HTTPBasicAuth(username, app_password)


def request_json(base_url: str, auth: HTTPBasicAuth, path: str) -> requests.Response:
    url = f"{base_url}{path}"
    return requests.get(url, auth=auth, timeout=REQUEST_TIMEOUT)


def looks_like_json(response: requests.Response) -> bool:
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "json" in content_type:
        return True
    stripped = response.text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def get_structure_type(payload: Any) -> str:
    if isinstance(payload, list):
        return "list"
    if isinstance(payload, dict):
        return "dict"
    return type(payload).__name__


def route_matches(route_name: str) -> bool:
    lowered = route_name.lower()
    return any(keyword in lowered for keyword in ROUTE_KEYWORDS)


def extract_allowed_methods(route_info: Any) -> list[str]:
    if not isinstance(route_info, dict):
        return []

    endpoints = route_info.get("endpoints")
    if not isinstance(endpoints, list):
        return []

    methods: list[str] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        endpoint_methods = endpoint.get("methods")
        if isinstance(endpoint_methods, list):
            methods.extend(str(method) for method in endpoint_methods)
        elif isinstance(endpoint_methods, dict):
            methods.extend(str(method) for method in endpoint_methods.keys())

    return sorted(set(methods))


def sanitize_string(value: str, key: str) -> str:
    lowered = key.lower()
    if not value:
        return value
    if any(keyword in lowered for keyword in SENSITIVE_KEYWORDS):
        return "[REDACTED]"
    if "://" in value:
        parsed = urlparse(value)
        if parsed.query:
            return "[REDACTED_URL]"
    if re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        return "[REDACTED]"
    if re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", value):
        return "[REDACTED]"
    if "mozilla/" in value.lower():
        return "[REDACTED]"
    return value


def sanitize_payload(payload: Any, key: str = "") -> Any:
    if isinstance(payload, dict):
        sanitized = {}
        for item_key, item_value in payload.items():
            normalized = str(item_key).lower()
            if isinstance(item_value, (dict, list)):
                sanitized[item_key] = sanitize_payload(item_value, normalized)
            elif isinstance(item_value, str):
                sanitized[item_key] = sanitize_string(item_value, normalized)
            else:
                sanitized[item_key] = item_value
        return sanitized

    if isinstance(payload, list):
        return [sanitize_payload(item, key) for item in payload]

    if isinstance(payload, str):
        return sanitize_string(payload, key)

    return payload


def analyze_index(base_url: str, auth: HTTPBasicAuth) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    response = request_json(base_url, auth, "/wp-json/")
    if response.status_code != 200:
        raise RuntimeError(f"/wp-json/ devolvio HTTP {response.status_code}.")
    if not looks_like_json(response):
        raise RuntimeError("/wp-json/ no devolvio una respuesta JSON.")

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("/wp-json/ devolvio JSON invalido.") from exc

    routes = payload.get("routes") if isinstance(payload, dict) else None
    if not isinstance(routes, dict):
        raise RuntimeError("/wp-json/ no incluyo un objeto 'routes' valido.")

    related_routes = []
    for route_name, route_info in routes.items():
        if route_matches(str(route_name)):
            methods = extract_allowed_methods(route_info)
            related_routes.append({"route": route_name, "methods": methods})

    return related_routes, routes


def probe_route(base_url: str, auth: HTTPBasicAuth, path: str) -> dict[str, Any]:
    response = request_json(base_url, auth, path)
    content_type = response.headers.get("Content-Type") or ""
    is_json = looks_like_json(response)
    structure_type = "unknown"
    record_count = None
    sample = None

    if is_json:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if payload is not None:
            structure_type = get_structure_type(payload)
            if isinstance(payload, list):
                record_count = len(payload)
                if payload:
                    sample = payload[:3]
            elif isinstance(payload, dict):
                sample = payload

    return {
        "route": path,
        "status_code": response.status_code,
        "content_type": content_type,
        "looks_like_json": is_json,
        "structure_type": structure_type,
        "record_count": record_count,
        "sample": sample,
    }


def main() -> None:
    base_url, auth = load_wordpress_config()
    related_routes, _routes_index = analyze_index(base_url, auth)

    print("Rutas relacionadas encontradas en /wp-json/:")
    if related_routes:
        for route in related_routes:
            methods = ", ".join(route["methods"]) if route["methods"] else "sin metodos declarados"
            print(f"{route['route']} | metodos: {methods}")
    else:
        print("No se encontraron rutas relacionadas con Tickera o tickets.")

    probe_results = []
    for route in PROBE_ROUTES:
        result = probe_route(base_url, auth, route)
        probe_results.append(result)
        records_label = (
            str(result["record_count"])
            if isinstance(result["record_count"], int)
            else "N/A"
        )
        print(
            f"ruta={result['route']} | http={result['status_code']} | "
            f"content_type={result['content_type'] or 'desconocido'} | "
            f"json={'si' if result['looks_like_json'] else 'no'} | "
            f"estructura={result['structure_type']} | registros={records_label}"
        )

    routes_with_data = []
    for result in probe_results:
        if result["sample"] is None:
            continue
        routes_with_data.append(
            {
                "route": result["route"],
                "status_code": result["status_code"],
                "content_type": result["content_type"],
                "structure_type": result["structure_type"],
                "record_count": result["record_count"],
                "sample": sanitize_payload(result["sample"]),
            }
        )

    if routes_with_data:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(
            json.dumps(
                {
                    "related_routes": related_routes,
                    "routes_with_data": routes_with_data,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"Muestra anonimizada guardada en: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
