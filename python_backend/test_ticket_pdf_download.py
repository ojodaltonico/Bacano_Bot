from __future__ import annotations

import getpass
import re
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import requests


DEBUG_DIR = Path(__file__).resolve().parent / "debug"
OUTPUT_FILE = DEBUG_DIR / "tickera_ticket_test.pdf"
REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def safe_final_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def extract_html_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    title = unescape(match.group(1)).strip()
    title = re.sub(r"\s+", " ", title)
    if not title:
        return None
    return title[:200]


def is_valid_pdf(content: bytes, content_type: str) -> bool:
    return content.startswith(b"%PDF") or "application/pdf" in content_type.lower()


def download_ticket_pdf(download_url: str) -> None:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/pdf,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        response = requests.get(
            download_url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Error al descargar el ticket: {exc}") from exc

    final_url = safe_final_url(response.url)
    content_type = (response.headers.get("Content-Type") or "").strip()
    content = response.content
    size_bytes = len(content)
    starts_with_pdf = content.startswith(b"%PDF")

    print(f"HTTP final: {response.status_code}")
    print(f"Content-Type: {content_type or 'desconocido'}")
    print(f"Tamaño descargado: {size_bytes} bytes")
    print(f"Comienza con %PDF: {'si' if starts_with_pdf else 'no'}")
    print(f"URL final segura: {final_url}")

    if is_valid_pdf(content, content_type):
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_bytes(content)
        print(f"PDF valido guardado en: {OUTPUT_FILE}")
        return

    if "html" in content_type.lower() or content.lstrip().lower().startswith(b"<!doctype html") or content.lstrip().lower().startswith(b"<html"):
        print("Se recibio HTML en lugar de PDF.")
        try:
            html_text = content.decode(response.encoding or "utf-8", errors="ignore")
        except LookupError:
            html_text = content.decode("utf-8", errors="ignore")
        title = extract_html_title(html_text)
        if title:
            print(f"Titulo de la pagina: {title}")
        else:
            print("Titulo de la pagina: no disponible")
        return

    print("La descarga no parece ser un PDF valido.")


def main() -> None:
    download_url = getpass.getpass("Pegá la URL completa de descarga del ticket: ").strip()
    if not download_url:
        raise SystemExit("No se ingreso ninguna URL.")

    download_ticket_pdf(download_url)


if __name__ == "__main__":
    main()
