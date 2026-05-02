from __future__ import annotations

import datetime as dt
import re
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from cleaner import clean_review_text

STORE_BASE = "https://store.steampowered.com"


@dataclass
class ScrapeResult:
    reviews: List[dict]
    game_name: Optional[str]
    age_gate_blocked: bool
    error: Optional[str] = None


class SteamReviewScraper:
    def __init__(self, session: Optional[requests.Session] = None, request_delay: float = 0.4):
        self.session = session or requests.Session()
        self.request_delay = request_delay
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
            }
        )

    def scrape_reviews(
        self,
        app_id: int,
        pages: int = 3,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> ScrapeResult:
        game_name, age_blocked, err = self._get_game_name_with_age_gate(app_id)
        if err:
            return ScrapeResult([], None, age_blocked, err)

        all_reviews: List[dict] = []
        cursor = "*"

        for page in range(1, pages + 1):
            if progress_callback:
                progress_callback(page, pages)

            page_reviews, cursor, html_extras, page_error = self._fetch_review_page(app_id, cursor)
            if page_error:
                return ScrapeResult(all_reviews, game_name, False, page_error)

            if not page_reviews:
                break

            all_reviews.extend(
                self._normalize_review_row(
                    app_id=app_id,
                    game_name=game_name,
                    payload=review,
                    html_extra=html_extras.get(str(review.get("recommendationid")), {}),
                )
                for review in page_reviews
            )
            time.sleep(self.request_delay)

        return ScrapeResult(all_reviews, game_name, False, None)

    def _fetch_review_page(
        self, app_id: int, cursor: str
    ) -> Tuple[List[dict], str, Dict[str, dict], Optional[str]]:
        encoded_cursor = quote(cursor, safe="")
        url = (
            f"{STORE_BASE}/appreviews/{app_id}"
            f"?json=1&language=all&day_range=365&filter=recent"
            f"&purchase_type=all&num_per_page=100&cursor={encoded_cursor}"
        )
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            return [], cursor, {}, f"Error de red al consultar reviews: {exc}"
        except ValueError as exc:
            return [], cursor, {}, f"No se pudo parsear respuesta JSON de reviews: {exc}"

        if payload.get("success") != 1:
            return [], cursor, {}, "Steam no devolvió reviews válidas para este App ID."

        extras = self._extract_html_review_extras(payload.get("html", ""))
        return payload.get("reviews", []), payload.get("cursor", cursor), extras, None

    def _get_game_name_with_age_gate(self, app_id: int) -> Tuple[Optional[str], bool, Optional[str]]:
        app_url = f"{STORE_BASE}/app/{app_id}/"
        try:
            self.session.get(STORE_BASE, timeout=20)
            response = self.session.get(app_url, allow_redirects=True, timeout=20)
            response.raise_for_status()
        except requests.RequestException as exc:
            return None, False, f"No se pudo abrir la página del juego: {exc}"

        if self._is_age_gate(response):
            passed, pass_error = self._try_bypass_age_gate(app_id)
            if not passed:
                return None, True, (
                    pass_error
                    or "El juego tiene age gate y no fue posible omitirlo automáticamente."
                )
            try:
                response = self.session.get(app_url, allow_redirects=True, timeout=20)
                response.raise_for_status()
            except requests.RequestException as exc:
                return None, True, f"Error al reintentar la página tras age gate: {exc}"

            if self._is_age_gate(response):
                return (
                    None,
                    True,
                    "Steam mantiene la verificación de edad para este juego. No se pudo continuar.",
                )

        soup = BeautifulSoup(response.text, "html.parser")
        title_node = soup.select_one("#appHubAppName")
        if title_node:
            return title_node.get_text(strip=True), False, None
        # Fallback si Steam cambia selectores
        og_title = soup.select_one("meta[property='og:title']")
        if og_title and og_title.get("content"):
            return og_title["content"].strip(), False, None
        return f"app_{app_id}", False, None

    def _is_age_gate(self, response: requests.Response) -> bool:
        url = (response.url or "").lower()
        html = (response.text or "").lower()
        return "agecheck" in url or "please enter your birth date" in html

    def _try_bypass_age_gate(self, app_id: int) -> Tuple[bool, Optional[str]]:
        """
        Estrategia principal:
        1) setear cookies de edad comunes usadas por Steam
        2) llamar agecheckset endpoint para registrar fecha de nacimiento
        """
        try:
            now_ts = int(time.time())
            self.session.cookies.set("birthtime", "631152000", domain="store.steampowered.com")
            self.session.cookies.set("lastagecheckage", "1-January-1990", domain="store.steampowered.com")
            self.session.cookies.set("wants_mature_content", "1", domain="store.steampowered.com")
            self.session.cookies.set("mature_content", "1", domain="store.steampowered.com")
            self.session.cookies.set("steamCountry", "US%7C5dfebdfb8f5a2f8a8f5f0f3e0c0a0a0a", domain="store.steampowered.com")
            self.session.cookies.set("sessionid", str(now_ts), domain="store.steampowered.com")

            age_set_url = f"{STORE_BASE}/agecheckset/app/{app_id}/"
            payload = {
                "sessionid": str(now_ts),
                "ageDay": "1",
                "ageMonth": "January",
                "ageYear": "1990",
            }
            response = self.session.post(age_set_url, data=payload, timeout=20, allow_redirects=True)
            if response.status_code >= 400:
                return False, f"Steam rechazó agecheckset con código {response.status_code}."
            return True, None
        except requests.RequestException as exc:
            return False, f"Error al intentar omitir age gate: {exc}"

    def _normalize_review_row(
        self,
        app_id: int,
        game_name: Optional[str],
        payload: dict,
        html_extra: Optional[dict] = None,
    ) -> dict:
        html_extra = html_extra or {}
        # Priorizamos fecha de creación real de la review y usamos "updated" como fallback.
        raw_timestamp = payload.get("timestamp_created") or payload.get("timestamp_updated")
        timestamp = self._normalize_timestamp(raw_timestamp)
        review_date = dt.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d") if timestamp else ""

        review_text = clean_review_text(payload.get("review", ""))
        voted_up = bool(payload.get("voted_up"))
        hours = (payload.get("author") or {}).get("playtime_forever", 0) / 60.0
        is_recent = False
        if timestamp:
            days = (dt.datetime.utcnow() - dt.datetime.utcfromtimestamp(timestamp)).days
            is_recent = days <= 30

        return {
            "app_id": app_id,
            "juego": game_name or f"app_{app_id}",
            "review_id": str(payload.get("recommendationid", "")),
            "fecha": review_date,
            "comentario": review_text,
            "recomendacion": "recommended" if voted_up else "not recommended",
            "horas_jugadas": round(hours, 2),
            "horas_en_review": html_extra.get("hours_at_review_time"),
            "publicada_recientemente": is_recent,
            "idioma": payload.get("language", ""),
            "votos_util": html_extra.get("helpful_count", 0),
            "votos_divertido": html_extra.get("funny_count", 0),
            "fuente_compra": html_extra.get("purchase_source", ""),
            "fecha_scraping": dt.datetime.utcnow().strftime("%Y-%m-%d"),
        }

    def _extract_html_review_extras(self, html: str) -> Dict[str, dict]:
        """
        Parsea el HTML embebido del endpoint /appreviews para enriquecer campos
        que no siempre vienen limpios en el JSON base.
        """
        if not html:
            return {}
        soup = BeautifulSoup(html, "html.parser")
        boxes = soup.select("div.ReviewContentCtn")
        extras: Dict[str, dict] = {}
        for box in boxes:
            review_id = self._extract_review_id_from_node(box.get("id", ""))
            if not review_id:
                continue

            vote_info_text = box.select_one("div.vote_info")
            hours_text = box.select_one("div.hours")
            purchase_source = box.select_one("div.responsive_purchase_source")

            vote_raw = vote_info_text.get_text(" ", strip=True) if vote_info_text else ""
            hours_raw = hours_text.get_text(" ", strip=True) if hours_text else ""
            purchase_raw = purchase_source.get_text(" ", strip=True) if purchase_source else ""

            extras[review_id] = {
                "helpful_count": self._extract_vote_count(vote_raw, vote_type="helpful"),
                "funny_count": self._extract_vote_count(vote_raw, vote_type="funny"),
                "hours_at_review_time": self._extract_hours_at_review_time(hours_raw),
                "purchase_source": purchase_raw,
            }
        return extras

    @staticmethod
    def _extract_review_id_from_node(node_id: str) -> Optional[str]:
        match = re.search(r"ReviewContent(?:all)?(\d+)", node_id or "")
        if not match:
            return None
        return match.group(1)

    @staticmethod
    def _extract_vote_count(text: str, vote_type: str) -> int:
        if not text:
            return 0
        if vote_type == "helpful":
            match = re.search(r"(\d+)\s+people?\s+found\s+this\s+review\s+helpful", text, re.IGNORECASE)
        else:
            match = re.search(r"(\d+)\s+people?\s+found\s+this\s+review\s+funny", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        # Steam a veces usa "1 person found..."
        if vote_type == "helpful" and re.search(r"\b1\s+person\s+found\s+this\s+review\s+helpful\b", text, re.IGNORECASE):
            return 1
        if vote_type == "funny" and re.search(r"\b1\s+person\s+found\s+this\s+review\s+funny\b", text, re.IGNORECASE):
            return 1
        return 0

    @staticmethod
    def _extract_hours_at_review_time(hours_raw: str) -> Optional[float]:
        if not hours_raw:
            return None
        match = re.search(r"\(([\d.,]+)\s*hrs?\s+at\s+review\s+time\)", hours_raw, re.IGNORECASE)
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _normalize_timestamp(value: Optional[object]) -> Optional[int]:
        """Normaliza epoch timestamp (segundos o milisegundos) a segundos."""
        if value is None:
            return None
        try:
            ts = int(value)
        except (TypeError, ValueError):
            return None

        # Si viene en milisegundos, convertimos a segundos.
        if ts > 10_000_000_000:
            ts = ts // 1000
        if ts <= 0:
            return None
        return ts
