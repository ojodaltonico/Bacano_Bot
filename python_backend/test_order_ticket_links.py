from __future__ import annotations

import json
import re
import sys
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config_manager import load_config
from integrations.woocommerce_client import WooCommerceClient


DEBUG_DIR = Path(__file__).resolve().parent / "debug"
REQUEST_TIMEOUT = 30
KEYWORDS = ("ticket", "entrada", "download", "descargar")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def sanitize_link_text(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return ""
    if "@" in normalized:
        return "[REDACTED]"
    if re.search(r"\b\d{7,}\b", normalized):
        return "[REDACTED]"
    return normalized[:120]


def parse_order_id(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit(
            "Uso: python python_backend/test_order_ticket_links.py <woocommerce_order_id>"
        )

    raw_value = argv[1].strip()
    if not raw_value.isdigit():
        raise SystemExit("El ID del pedido WooCommerce debe ser numerico.")

    return int(raw_value)


def build_order_received_url(base_url: str, order_id: int, order_key: str) -> str:
    return f"{base_url}/checkout/order-received/{order_id}/?key={order_key}"


def fetch_order(order_id: int) -> tuple[WooCommerceClient, dict[str, Any]]:
    client = WooCommerceClient()
    order = client.get_order(order_id)
    if not isinstance(order, dict):
        raise RuntimeError("WooCommerce no devolvio un pedido valido.")
    return client, order


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_order_page(session: requests.Session, url: str) -> requests.Response:
    try:
        return session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        raise RuntimeError(f"Error consultando la pagina order-received: {exc}") from exc


def is_html_response(response: requests.Response) -> bool:
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "html" in content_type:
        return True
    stripped = response.text.lstrip().lower()
    return stripped.startswith("<!doctype html") or stripped.startswith("<html")


def extract_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    if not soup.title or not soup.title.string:
        return None
    return " ".join(unescape(soup.title.string).split())[:200]


def extract_ticket_links(html: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, Any]] = []

    for position, anchor in enumerate(soup.find_all("a", href=True), start=1):
        href = str(anchor.get("href") or "")
        absolute_url = urljoin(base_url, href)
        parsed = urlparse(absolute_url)
        params = parse_qs(parsed.query)

        if not all(
            key in params and params[key]
            for key in ("download_ticket", "order_key", "nonce")
        ):
            continue

        results.append(
            {
                "position": position,
                "ticket_instance_id": str(params["download_ticket"][0]),
                "has_order_key": True,
                "has_nonce": True,
                "link_text": sanitize_link_text(anchor.get_text(" ", strip=True)),
            }
        )

    return results


def find_keywords(html: str) -> list[str]:
    lowered = html.lower()
    return [keyword for keyword in KEYWORDS if keyword in lowered]


def analyze_page(response: requests.Response, base_url: str) -> dict[str, Any]:
    html = response.text
    received_html = is_html_response(response)
    title = extract_title(html) if received_html else None
    keywords_found = find_keywords(html) if received_html else []
    ticket_links = extract_ticket_links(html, base_url) if received_html else []
    return {
        "received_html": received_html,
        "page_title": title,
        "keywords_found": keywords_found,
        "ticket_links": ticket_links,
    }


def load_wordpress_login_config() -> tuple[str, str, str]:
    config = load_config()
    wordpress_config = config.get("wordpress")
    if not isinstance(wordpress_config, dict):
        raise RuntimeError("Falta la seccion 'wordpress' en la configuracion.")

    base_url = str(wordpress_config.get("base_url", "")).strip().rstrip("/")
    username = str(wordpress_config.get("username", "")).strip()
    password = str(wordpress_config.get("password", "")).strip()

    if not base_url:
        raise RuntimeError("Falta 'wordpress.base_url' en la configuracion.")
    if not username:
        raise RuntimeError("Falta 'wordpress.username' en la configuracion.")
    if not password:
        raise RuntimeError(
            "Falta 'wordpress.password' en la configuracion para la fase con login."
        )

    return base_url, username, password


def login_to_wordpress(session: requests.Session, base_url: str, username: str, password: str) -> bool:
    login_url = f"{base_url}/wp-login.php"
    payload = {
        "log": username,
        "pwd": password,
        "rememberme": "forever",
        "wp-submit": "Acceder",
    }

    try:
        session.post(login_url, data=payload, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        raise RuntimeError(f"Error iniciando sesion en WordPress: {exc}") from exc

    return any("wordpress_logged_in" in cookie.name for cookie in session.cookies)


def build_output_payload(
    order: dict[str, Any],
    public_phase: dict[str, Any],
    login_successful: bool,
    authenticated_phase: dict[str, Any] | None,
    login_error: str | None,
) -> dict[str, Any]:
    billing = order.get("billing") or {}
    return {
        "order_id": order.get("id"),
        "status": order.get("status"),
        "date_paid": order.get("date_paid"),
        "payment_method": order.get("payment_method"),
        "billing_phone_present": bool(billing.get("phone")),
        "login_successful": login_successful,
        "login_error": login_error,
        "without_login": {
            "received_html": public_phase["received_html"],
            "page_title": public_phase["page_title"],
            "keywords_found": public_phase["keywords_found"],
            "ticket_link_count": len(public_phase["ticket_links"]),
            "ticket_links": public_phase["ticket_links"],
        },
        "with_login": (
            {
                "received_html": authenticated_phase["received_html"],
                "page_title": authenticated_phase["page_title"],
                "keywords_found": authenticated_phase["keywords_found"],
                "ticket_link_count": len(authenticated_phase["ticket_links"]),
                "ticket_links": authenticated_phase["ticket_links"],
            }
            if authenticated_phase is not None
            else None
        ),
    }


def print_link_summary(prefix: str, links: list[dict[str, Any]]) -> None:
    for link in links:
        print(
            f"{prefix} ticket_instance_id={link['ticket_instance_id']} | "
            f"order_key=si | nonce=si | posicion={link['position']}"
        )


def main() -> None:
    order_id = parse_order_id(sys.argv)
    client, order = fetch_order(order_id)

    order_key = str(order.get("order_key") or "").strip()
    if not order_key:
        raise RuntimeError("El pedido no incluye order_key.")

    order_received_url = build_order_received_url(client.base_url, order_id, order_key)

    public_session = create_session()
    public_response = fetch_order_page(public_session, order_received_url)
    public_phase = analyze_page(public_response, client.base_url)

    login_successful = False
    authenticated_phase: dict[str, Any] | None = None
    login_error: str | None = None

    if len(public_phase["ticket_links"]) == 0:
        try:
            base_url, username, password = load_wordpress_login_config()
            authenticated_session = create_session()
            login_successful = login_to_wordpress(
                authenticated_session, base_url, username, password
            )

            if login_successful:
                authenticated_response = fetch_order_page(
                    authenticated_session, order_received_url
                )
                authenticated_phase = analyze_page(
                    authenticated_response, client.base_url
                )
        except RuntimeError as exc:
            login_error = str(exc)

    payment_confirmed = "si" if bool(order.get("date_paid")) else "no"

    print(f"ID del pedido: {order.get('id', order_id)}")
    print(f"Estado: {order.get('status', 'N/A')}")
    print(f"Pago confirmado: {payment_confirmed}")
    print(
        f"Login exitoso: {'si' if login_successful else 'no'}"
    )
    if login_error:
        print(f"Fase con login no ejecutada: {login_error}")
    print(
        f"Cantidad de enlaces encontrados sin login: {len(public_phase['ticket_links'])}"
    )
    print_link_summary("Sin login:", public_phase["ticket_links"])

    authenticated_links = authenticated_phase["ticket_links"] if authenticated_phase else []
    print(
        f"Cantidad de enlaces encontrados con login: {len(authenticated_links)}"
    )
    print_link_summary("Con login:", authenticated_links)

    if not public_phase["ticket_links"] and not authenticated_links:
        final_phase = authenticated_phase or public_phase
        print(f"Se recibio HTML: {'si' if final_phase['received_html'] else 'no'}")
        print(f"Titulo de la pagina: {final_phase['page_title'] or 'no disponible'}")
        keywords_summary = (
            ", ".join(final_phase["keywords_found"])
            if final_phase["keywords_found"]
            else "ninguna"
        )
        print(f"Palabras detectadas: {keywords_summary}")

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    output_file = DEBUG_DIR / f"order_{order_id}_ticket_links_sample.json"
    output_file.write_text(
        json.dumps(
            build_output_payload(
                order,
                public_phase,
                login_successful,
                authenticated_phase,
                login_error,
            ),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
