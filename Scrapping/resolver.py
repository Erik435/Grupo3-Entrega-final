from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from utils import extract_app_id_from_url, is_app_id, normalize_game_input


STEAM_BASE = "https://store.steampowered.com"


@dataclass
class ResolveResult:
    app_id: Optional[int]
    game_name: Optional[str]
    source: str
    error: Optional[str] = None


class SteamGameResolver:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
            }
        )

    def resolve(self, user_input: str) -> ResolveResult:
        value = normalize_game_input(user_input)
        if not value:
            return ResolveResult(None, None, "empty", "Debes ingresar un nombre, URL o App ID.")

        url_app_id = extract_app_id_from_url(value)
        if url_app_id:
            return ResolveResult(url_app_id, None, "url")

        if is_app_id(value):
            return ResolveResult(int(value), None, "app_id")

        return self._resolve_from_game_name(value)

    def _resolve_from_game_name(self, game_name: str) -> ResolveResult:
        suggest_url = (
            f"{STEAM_BASE}/search/suggest?term={quote_plus(game_name)}"
            "&f=games&cc=US&realm=1&l=english"
        )
        try:
            response = self.session.get(suggest_url, timeout=20)
            response.raise_for_status()
        except requests.RequestException as exc:
            return ResolveResult(None, None, "name", f"Error de red al buscar juego: {exc}")

        soup = BeautifulSoup(response.text, "html.parser")
        first_item = soup.select_one("a.match")
        if not first_item:
            return ResolveResult(
                None,
                None,
                "name",
                f"No se encontró un juego para '{game_name}' en Steam.",
            )

        app_id_attr = first_item.get("data-ds-appid")
        title_node = first_item.select_one(".match_name")
        if not app_id_attr:
            href = first_item.get("href", "")
            app_id_attr = str(extract_app_id_from_url(href) or "")

        if not app_id_attr.isdigit():
            return ResolveResult(
                None,
                None,
                "name",
                "No se pudo resolver un App ID válido desde la búsqueda de Steam.",
            )

        resolved_name = title_node.get_text(strip=True) if title_node else game_name
        return ResolveResult(int(app_id_attr), resolved_name, "name")
