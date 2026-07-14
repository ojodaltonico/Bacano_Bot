from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config_manager import load_config
from integrations.tickera_client import TickeraClient
from integrations.woocommerce_client import WooCommerceClient


REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class TicketDeliveryService:
    def __init__(self) -> None:
        self._woocommerce_client = WooCommerceClient()
        self._tickera_client = TickeraClient()
        self._wordpress_base_url: str | None = None
        self._wordpress_username: str | None = None
        self._wordpress_password: str | None = None

    def get_order_delivery_info(self, order_id: int) -> dict[str, Any]:
        order = self._get_order(order_id)
        billing = order.get("billing") or {}
        line_items = order.get("line_items") or []
        expected_tickets = sum(
            int(item.get("quantity") or 0)
            for item in line_items
            if isinstance(item, dict)
        )
        product_names = [
            str(item.get("name") or "")
            for item in line_items
            if isinstance(item, dict) and item.get("name")
        ]

        payment_method = str(order.get("payment_method") or "")
        status = str(order.get("status") or "")
        date_paid = order.get("date_paid")
        needs_payment = bool(order.get("needs_payment"))
        billing_phone = str(billing.get("phone") or "").strip()

        is_mercado_pago = payment_method == "woo-mercado-pago-custom"
        is_cash = payment_method == "cod"
        ready_to_send = (
            is_mercado_pago
            and status in {"processing", "completed"}
            and date_paid is not None
            and not needs_payment
            and bool(billing_phone)
        )

        return {
            "order_id": order.get("id"),
            "status": status,
            "date_paid": date_paid,
            "payment_method": payment_method,
            "payment_method_title": order.get("payment_method_title"),
            "billing_phone": billing_phone,
            "billing_email": str(billing.get("email") or "").strip(),
            "billing_first_name": str(billing.get("first_name") or "").strip(),
            "billing_last_name": str(billing.get("last_name") or "").strip(),
            "expected_tickets": expected_tickets,
            "product_names": product_names,
            "is_mercado_pago": is_mercado_pago,
            "is_cash": is_cash,
            "ready_to_send": ready_to_send,
        }

    def get_ticket_download_links(self, order_id: int) -> list[dict[str, Any]]:
        order = self._get_order(order_id)
        order_key = str(order.get("order_key") or "").strip()
        if not order_key:
            raise RuntimeError("El pedido no incluye order_key.")

        session = self._create_session()
        if not self._login_to_wordpress(session):
            raise RuntimeError("No se pudo iniciar sesion en WordPress.")

        return self._get_ticket_download_links_with_session(order_id, order_key, session)

    def download_ticket_pdfs(self, order_id: int, destination_dir: str | Path) -> list[str]:
        downloaded_tickets = self._download_ticket_pdf_records(order_id, destination_dir)
        return [ticket["pdf_path"] for ticket in downloaded_tickets]

    def prepare_order_tickets(
        self, order_id: int, destination_dir: str | Path
    ) -> dict[str, Any]:
        delivery_info = self.get_order_delivery_info(order_id)
        if not delivery_info["ready_to_send"]:
            return {"ready": False, "reason": "El pedido no esta listo para enviar."}

        expected_tickets = int(delivery_info["expected_tickets"])
        try:
            downloaded_tickets = self._download_ticket_pdf_records(
                order_id, destination_dir
            )
        except RuntimeError as exc:
            return {"ready": False, "reason": str(exc)}

        found_tickets = len(downloaded_tickets)
        if found_tickets < expected_tickets:
            return {
                "ready": False,
                "reason": (
                    "Se encontraron menos tickets de los esperados "
                    f"({found_tickets}/{expected_tickets})."
                ),
            }

        customer_name = " ".join(
            part
            for part in (
                delivery_info["billing_first_name"],
                delivery_info["billing_last_name"],
            )
            if part
        ).strip()

        return {
            "ready": True,
            "order_id": delivery_info["order_id"],
            "phone": delivery_info["billing_phone"],
            "customer_name": customer_name,
            "expected_tickets": expected_tickets,
            "found_tickets": found_tickets,
            "ticket_pdfs": downloaded_tickets,
            "pdf_files": [ticket["pdf_path"] for ticket in downloaded_tickets],
            "reason": None,
        }

    def _download_ticket_pdf_records(
        self, order_id: int, destination_dir: str | Path
    ) -> list[dict[str, Any]]:
        order = self._get_order(order_id)
        order_key = str(order.get("order_key") or "").strip()
        if not order_key:
            raise RuntimeError("El pedido no incluye order_key.")

        session = self._create_session()
        if not self._login_to_wordpress(session):
            raise RuntimeError("No se pudo iniciar sesion en WordPress.")

        ticket_links = self._get_ticket_download_links_with_session(order_id, order_key, session)
        ticket_metadata = self._get_tickera_ticket_metadata(order_id)
        ticket_downloads = self._merge_links_with_tickets(order_id, ticket_links, ticket_metadata)
        if not ticket_downloads:
            return []

        target_dir = Path(destination_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        downloaded_tickets: list[dict[str, Any]] = []
        for ticket_download in ticket_downloads:
            output_path = target_dir / self._build_ticket_filename(
                order_id,
                ticket_download["transaction_id"],
                ticket_download["buyer_first"],
                ticket_download["buyer_last"],
            )
            if output_path.exists():
                raise RuntimeError(f"El archivo destino ya existe: {output_path}")

            response = self._download_pdf_response(session, ticket_download["download_url"])
            if not self._is_valid_pdf(
                response.content, response.headers.get("Content-Type", "")
            ):
                raise RuntimeError(
                    f"La descarga del ticket {ticket_download['transaction_id']} no es un PDF valido."
                )

            output_path.write_bytes(response.content)
            downloaded_tickets.append(
                {
                    "transaction_id": ticket_download["transaction_id"],
                    "ticket_holder_name": self._build_holder_name(
                        ticket_download["buyer_first"],
                        ticket_download["buyer_last"],
                    ),
                    "ticket_type": ticket_download["ticket_type"],
                    "event_name": ticket_download["event_name"],
                    "holder_source": ticket_download["holder_source"],
                    "raw_ticket_keys": ticket_download["raw_ticket_keys"],
                    "normalized_ticket_keys": ticket_download["normalized_ticket_keys"],
                    "buyer_first_debug": ticket_download["buyer_first"],
                    "buyer_last_debug": ticket_download["buyer_last"],
                    "buyer_name_custom_field_debug": ticket_download["buyer_name_custom_field"],
                    "pdf_path": str(output_path),
                }
            )

        return downloaded_tickets

    def _get_ticket_download_links_with_session(
        self, order_id: int, order_key: str, session: requests.Session
    ) -> list[dict[str, Any]]:
        order_received_url = self._build_order_received_url(order_id, order_key)
        response = self._fetch_order_page(session, order_received_url)
        if not self._is_html_response(response):
            raise RuntimeError("La pagina order-received no devolvio HTML.")

        ticket_links = self._extract_ticket_links(response.text)
        ticket_links.sort(key=lambda item: item["position"])
        return ticket_links

    def _load_wordpress_login_config(self) -> tuple[str, str, str]:
        config = load_config()
        wordpress_config = config.get("wordpress")
        if not isinstance(wordpress_config, dict):
            raise RuntimeError("Falta la seccion 'wordpress' en la configuracion.")

        base_url = str(wordpress_config.get("base_url", "")).strip().rstrip("/")
        username = str(wordpress_config.get("username", "")).strip()
        password = str(wordpress_config.get("password", "")).strip()

        missing_fields = [
            field
            for field, value in (
                ("base_url", base_url),
                ("username", username),
                ("password", password),
            )
            if not value
        ]
        if missing_fields:
            raise RuntimeError(
                "Faltan campos requeridos en 'wordpress': " + ", ".join(missing_fields)
            )

        return base_url, username, password

    def _ensure_wordpress_login_config(self) -> None:
        if (
            self._wordpress_base_url
            and self._wordpress_username
            and self._wordpress_password
        ):
            return

        (
            self._wordpress_base_url,
            self._wordpress_username,
            self._wordpress_password,
        ) = self._load_wordpress_login_config()

    def _get_order(self, order_id: int) -> dict[str, Any]:
        order = self._woocommerce_client.get_order(order_id)
        if not isinstance(order, dict):
            raise RuntimeError("WooCommerce no devolvio un pedido valido.")
        return order

    def _build_order_received_url(self, order_id: int, order_key: str) -> str:
        return (
            f"{self._woocommerce_client.base_url}/checkout/order-received/"
            f"{order_id}/?key={order_key}"
        )

    @staticmethod
    def _create_session() -> requests.Session:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        return session

    def _login_to_wordpress(self, session: requests.Session) -> bool:
        self._ensure_wordpress_login_config()
        login_url = f"{self._wordpress_base_url}/wp-login.php"
        payload = {
            "log": self._wordpress_username,
            "pwd": self._wordpress_password,
            "rememberme": "forever",
            "wp-submit": "Acceder",
        }

        try:
            session.post(
                login_url,
                data=payload,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Error iniciando sesion en WordPress: {exc}") from exc

        return any("wordpress_logged_in" in cookie.name for cookie in session.cookies)

    @staticmethod
    def _fetch_order_page(session: requests.Session, url: str) -> requests.Response:
        try:
            return session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Error consultando la pagina order-received: {exc}"
            ) from exc

    def _extract_ticket_links(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[dict[str, Any]] = []

        for position, anchor in enumerate(soup.find_all("a", href=True), start=1):
            href = str(anchor.get("href") or "")
            absolute_url = urljoin(self._woocommerce_client.base_url, href)
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
                    "download_url": absolute_url,
                }
            )

        return results

    def _get_tickera_ticket_metadata(self, order_id: int) -> list[dict[str, Any]]:
        expected_prefix = f"{order_id}-"
        matched_tickets: list[dict[str, Any]] = []
        found_any = False

        for page in range(1, 21):
            tickets = self._tickera_client.get_tickets(per_page=50, page=page)
            if not tickets:
                break

            for ticket in tickets:
                if not isinstance(ticket, dict):
                    continue

                data = self._extract_ticket_data(ticket)
                if not data:
                    continue

                transaction_id = str(data.get("transaction_id") or "")
                if not transaction_id:
                    continue

                if transaction_id == str(order_id) or transaction_id.startswith(expected_prefix):
                    buyer_first = str(data.get("buyer_first") or "").strip()
                    buyer_last = str(data.get("buyer_last") or "").strip()
                    holder_source = "buyer_fields"
                    if not buyer_first or not buyer_last:
                        fallback_first, fallback_last = self._extract_holder_from_custom_fields(
                            data.get("custom_fields")
                        )
                        if fallback_first or fallback_last:
                            buyer_first = buyer_first or fallback_first
                            buyer_last = buyer_last or fallback_last
                            holder_source = "custom_fields"
                    if not buyer_first and not buyer_last:
                        holder_source = "fallback"

                    matched_tickets.append(
                        {
                            "transaction_id": transaction_id,
                            "buyer_first": buyer_first,
                            "buyer_last": buyer_last,
                            "checksum": str(data.get("checksum") or "").strip(),
                            "ticket_type": self._extract_custom_field_value(
                                data.get("custom_fields"), "Ticket Type"
                            ),
                            "event_name": self._extract_custom_field_value(
                                data.get("custom_fields"), "Event"
                            ),
                            "holder_source": holder_source,
                            "raw_ticket_keys": sorted(ticket.keys()),
                            "normalized_ticket_keys": sorted(data.keys()),
                            "buyer_name_custom_field": self._extract_custom_field_value(
                                data.get("custom_fields"), "Buyer Name"
                            ),
                        }
                    )
                    found_any = True

            if found_any:
                break

            if len(tickets) < 50:
                break

        matched_tickets.sort(
            key=lambda ticket: (
                self._extract_correlative(ticket["transaction_id"], order_id),
                ticket["transaction_id"],
            )
        )
        return matched_tickets

    @staticmethod
    def _extract_custom_field_value(custom_fields: Any, field_name: str) -> str:
        if not isinstance(custom_fields, list):
            return ""

        for entry in custom_fields:
            if (
                isinstance(entry, list)
                and len(entry) >= 2
                and str(entry[0]).strip().lower() == field_name.lower()
            ):
                return str(entry[1]).strip()
        return ""

    @staticmethod
    def _extract_correlative(transaction_id: str, order_id: int) -> int:
        order_id_text = str(order_id)
        if transaction_id == order_id_text:
            return 0
        if transaction_id.startswith(f"{order_id_text}-"):
            suffix = transaction_id.rsplit("-", 1)[-1]
            if suffix.isdigit():
                return int(suffix)
        return 999999

    def _merge_links_with_tickets(
        self,
        order_id: int,
        ticket_links: list[dict[str, Any]],
        ticket_metadata: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for index, ticket_link in enumerate(ticket_links):
            ticket_info = ticket_metadata[index] if index < len(ticket_metadata) else None
            transaction_id = (
                ticket_info["transaction_id"]
                if ticket_info
                else f"{order_id}-{index + 1}"
            )
            merged.append(
                {
                    "position": ticket_link["position"],
                    "ticket_instance_id": ticket_link["ticket_instance_id"],
                    "download_url": ticket_link["download_url"],
                    "transaction_id": transaction_id,
                    "buyer_first": ticket_info["buyer_first"] if ticket_info else "",
                    "buyer_last": ticket_info["buyer_last"] if ticket_info else "",
                    "checksum": ticket_info["checksum"] if ticket_info else "",
                    "ticket_type": ticket_info["ticket_type"] if ticket_info else "",
                    "event_name": ticket_info["event_name"] if ticket_info else "",
                    "holder_source": ticket_info["holder_source"] if ticket_info else "fallback",
                    "raw_ticket_keys": ticket_info["raw_ticket_keys"] if ticket_info else [],
                    "normalized_ticket_keys": ticket_info["normalized_ticket_keys"] if ticket_info else [],
                    "buyer_name_custom_field": (
                        ticket_info["buyer_name_custom_field"] if ticket_info else ""
                    ),
                }
            )
        return merged

    @staticmethod
    def _extract_ticket_data(ticket: Any) -> dict[str, Any]:
        if not isinstance(ticket, dict):
            return {}

        data = ticket.get("data")
        if isinstance(data, dict):
            return data

        return ticket

    def _extract_holder_from_custom_fields(
        self, custom_fields: Any
    ) -> tuple[str, str]:
        buyer_name = self._extract_custom_field_value(custom_fields, "Buyer Name")
        if not buyer_name:
            return "", ""

        parts = [part for part in buyer_name.split() if part]
        if not parts:
            return "", ""
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], " ".join(parts[1:])

    @staticmethod
    def _sanitize_filename_component(value: str) -> str:
        cleaned = value.strip().replace(" ", "_")
        for invalid_char in '<>:"/\\|?*':
            cleaned = cleaned.replace(invalid_char, "")
        cleaned = "_".join(part for part in cleaned.split("_") if part)
        return cleaned

    def _build_ticket_filename(
        self, order_id: int, transaction_id: str, buyer_first: str, buyer_last: str
    ) -> str:
        safe_first = self._sanitize_filename_component(buyer_first)
        safe_last = self._sanitize_filename_component(buyer_last)
        safe_transaction_id = self._sanitize_filename_component(transaction_id)
        if safe_first and safe_last and safe_transaction_id:
            return f"{safe_first}_{safe_last}_{safe_transaction_id}.pdf"
        fallback_id = safe_transaction_id or f"{order_id}-{self._extract_correlative(transaction_id, order_id)}"
        return f"Ticket_{fallback_id}.pdf"

    @staticmethod
    def _build_holder_name(buyer_first: str, buyer_last: str) -> str:
        full_name = " ".join(part for part in (buyer_first, buyer_last) if part).strip()
        return full_name or "N/A"

    @staticmethod
    def _is_html_response(response: requests.Response) -> bool:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "html" in content_type:
            return True
        stripped = response.text.lstrip().lower()
        return stripped.startswith("<!doctype html") or stripped.startswith("<html")

    @staticmethod
    def _download_pdf_response(
        session: requests.Session, download_url: str
    ) -> requests.Response:
        headers = {
            "Accept": (
                "application/pdf,text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            )
        }
        try:
            return session.get(
                download_url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Error descargando un ticket PDF: {exc}") from exc

    @staticmethod
    def _is_valid_pdf(content: bytes, content_type: str) -> bool:
        return content.startswith(b"%PDF") or "application/pdf" in content_type.lower()
