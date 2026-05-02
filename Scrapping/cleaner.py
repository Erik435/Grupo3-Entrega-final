import re

def clean_review_text(text: str) -> str:
    """
    Limpieza básica:
    - elimina saltos de línea innecesarios
    - elimina caracteres de control
    - normaliza espacios
    """
    if not text:
        return ""

    cleaned = text.replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]+", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()
