from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from requests.auth import HTTPBasicAuth

from config_manager import load_config


class WooCommerceConfigError(RuntimeError):
    """Raised when WooCommerce configuration is missing or invalid."""


class WooCommerceAPIError(RuntimeError):
    """Raised when WooCommerce returns an unexpected response."""


class WooCommerceClient:
    def __init__(self) -> None:
        config = load_config()
        woocommerce_config = config.get("woocommerce")
        wordpress_config = config.get("wordpress")

        if not isinstance(woocommerce_config, dict):
            raise WooCommerceConfigError(
                "Falta la seccion 'woocommerce' en la configuracion."
            )

        wordpress_base_url = ""
        if isinstance(wordpress_config, dict):
            wordpress_base_url = str(wordpress_config.get("base_url", "")).strip()

        self.base_url = str(
            woocommerce_config.get("base_url") or wordpress_base_url or ""
        ).strip().rstrip("/")
        self.consumer_key = str(woocommerce_config.get("consumer_key", "")).strip()
        self.consumer_secret = str(woocommerce_config.get("consumer_secret", "")).strip()

        missing_fields = [
            field
            for field, value in (
                ("base_url", self.base_url),
                ("consumer_key", self.consumer_key),
                ("consumer_secret", self.consumer_secret),
            )
            if not value
        ]
        if missing_fields:
            raise WooCommerceConfigError(
                "Faltan campos requeridos en 'woocommerce': "
                + ", ".join(missing_fields)
            )

        self._auth = HTTPBasicAuth(self.consumer_key, self.consumer_secret)
        self._timeout = 30

    def get_orders(
        self,
        status: Optional[str] = None,
        per_page: int = 10,
        page: int = 1,
        after: Optional[str] = None,
    ) -> Any:
        params: Dict[str, Any] = {
            "per_page": per_page,
            "page": page,
        }
        if status:
            params["status"] = status
        if after:
            params["after"] = after

        return self._get("/wp-json/wc/v3/orders", params=params)

    def get_order(self, order_id: int) -> Any:
        if not order_id:
            raise ValueError("order_id es requerido para consultar un pedido.")
        return self._get(f"/wp-json/wc/v3/orders/{order_id}")

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"

        try:
            response = requests.get(
                url,
                params=params,
                auth=self._auth,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise WooCommerceAPIError(
                f"Error consultando WooCommerce en '{path}': {exc}"
            ) from exc

        if response.status_code != 200:
            message = self._extract_error_message(response)
            raise WooCommerceAPIError(
                f"WooCommerce devolvio HTTP {response.status_code} en '{path}'. {message}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise WooCommerceAPIError(
                f"WooCommerce devolvio una respuesta no JSON en '{path}'."
            ) from exc

    @staticmethod
    def _extract_error_message(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return "Respuesta no JSON."

        if isinstance(payload, dict):
            code = payload.get("code")
            message = payload.get("message")
            if code and message:
                return f"{code}: {message}"
            if message:
                return str(message)

        return "Error sin detalle adicional."
