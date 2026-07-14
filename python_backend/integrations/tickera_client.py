from __future__ import annotations

from typing import Any

import requests

from config_manager import load_config


class TickeraConfigError(RuntimeError):
    """Raised when Tickera configuration is missing or invalid."""


class TickeraAPIError(RuntimeError):
    """Raised when Tickera returns an unexpected response."""


class TickeraClient:
    def __init__(self) -> None:
        config = load_config()
        tickera_config = config.get("tickera")

        if not isinstance(tickera_config, dict):
            raise TickeraConfigError("Falta la seccion 'tickera' en la configuracion.")

        self.base_url = str(tickera_config.get("base_url", "")).strip().rstrip("/")
        self.api_key = str(tickera_config.get("api_key", "")).strip()

        missing_fields = [
            field
            for field, value in (
                ("base_url", self.base_url),
                ("api_key", self.api_key),
            )
            if not value
        ]
        if missing_fields:
            raise TickeraConfigError(
                "Faltan campos requeridos en 'tickera': " + ", ".join(missing_fields)
            )

        self._timeout = 30

    def get_tickets(self, per_page: int = 50, page: int = 1) -> list[Any]:
        path = f"{self.api_key}/tickets_info/{per_page}/{page}/"
        return self._get(path)

    def _get(self, path: str) -> list[Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"

        try:
            response = requests.get(url, timeout=self._timeout)
        except requests.RequestException as exc:
            raise TickeraAPIError(
                f"Error consultando Tickera en '{self._safe_path(path)}': {exc}"
            ) from exc

        if response.status_code != 200:
            raise TickeraAPIError(
                f"Tickera devolvio HTTP {response.status_code} en '{self._safe_path(path)}'."
            )

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "html" in content_type:
            raise TickeraAPIError(
                f"Tickera devolvio HTML inesperado en '{self._safe_path(path)}'."
            )

        stripped = response.text.lstrip()
        if stripped.startswith("<!DOCTYPE html") or stripped.startswith("<html"):
            raise TickeraAPIError(
                f"Tickera devolvio HTML inesperado en '{self._safe_path(path)}'."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise TickeraAPIError(
                f"Tickera devolvio JSON invalido en '{self._safe_path(path)}'."
            ) from exc

        if not isinstance(payload, list):
            raise TickeraAPIError(
                f"Tickera devolvio una respuesta valida pero no es una lista en '{self._safe_path(path)}'."
            )

        return payload

    @staticmethod
    def _safe_path(path: str) -> str:
        return path.replace(path.split("/", 1)[0], "[REDACTED_API_KEY]", 1)
