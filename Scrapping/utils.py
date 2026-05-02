import io
import re
from typing import Optional

import pandas as pd


STEAM_APP_URL_RE = re.compile(r"store\.steampowered\.com\/app\/(\d+)", re.IGNORECASE)


def extract_app_id_from_url(value: str) -> Optional[int]:
    """Extrae App ID desde una URL de Steam si existe."""
    if not value:
        return None
    match = STEAM_APP_URL_RE.search(value.strip())
    if not match:
        return None
    return int(match.group(1))


def is_app_id(value: str) -> bool:
    """Valida si el texto parece un App ID numérico."""
    return bool(value and value.strip().isdigit())


def normalize_game_input(value: str) -> str:
    """Normaliza entrada libre del usuario."""
    return re.sub(r"\s+", " ", value or "").strip()


def clean_spaces(text: str) -> str:
    """Normaliza espacios repetidos."""
    return re.sub(r"\s+", " ", (text or "")).strip()


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Convierte DataFrame a bytes CSV UTF-8."""
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")
