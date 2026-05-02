"""Cliente HTTP para descargar HTML y medir tiempo de respuesta."""

from dataclasses import dataclass
from time import perf_counter

import httpx


class SiteFetchError(Exception):
    pass


@dataclass
class FetchResult:
    url: str
    status_code: int
    response_time_ms: float
    html: str


class WebScraper:
    """Encapsula solicitudes HTTP con configuración homogénea."""

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, url: str) -> FetchResult:
        """Descarga la URL objetivo y devuelve HTML, estado y latencia."""
        # Extracción del HTML con medición de latencia para usarla como métrica.
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; WebInsightAPI/1.0; +https://localhost)"
            )
        }
        try:
            start = perf_counter()
            with httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                headers=headers,
            ) as client:
                response = client.get(url)
            elapsed_ms = round((perf_counter() - start) * 1000, 2)
            return FetchResult(
                url=str(response.url),
                status_code=response.status_code,
                response_time_ms=elapsed_ms,
                html=response.text,
            )
        except httpx.RequestError as exc:
            raise SiteFetchError(f"Error de red al solicitar {url}: {exc}") from exc