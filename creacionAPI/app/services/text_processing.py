"""Extracción y transformación de contenido HTML a métricas cuantificables."""

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


@dataclass
class ExtractedData:
    title: str
    meta_description: str
    h1_count: int
    h2_count: int
    image_count: int
    images_without_alt: int
    internal_links: int
    external_links: int
    word_count: int
    main_text_excerpt: str


class TextProcessor:
    """Aplica limpieza HTML y cálculo de indicadores de contenido."""

    @staticmethod
    def extract_metrics(html: str, base_url: str) -> ExtractedData:
        """Obtiene metadatos, estructura, enlaces y texto procesado."""
        soup = BeautifulSoup(html, "html.parser")

        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        meta_description = (
            meta_tag.get("content", "").strip() if meta_tag else ""
        )

        h1_count = len(soup.find_all("h1"))
        h2_count = len(soup.find_all("h2"))

        images = soup.find_all("img")
        image_count = len(images)
        images_without_alt = sum(1 for img in images if not img.get("alt"))

        internal_links, external_links = TextProcessor._count_links(soup, base_url)
        clean_text = TextProcessor._clean_visible_text(soup)
        words = re.findall(r"\b\w+\b", clean_text, flags=re.UNICODE)
        word_count = len(words)
        excerpt = clean_text[:280].strip()
        if len(clean_text) > 280:
            excerpt += "..."

        return ExtractedData(
            title=title,
            meta_description=meta_description,
            h1_count=h1_count,
            h2_count=h2_count,
            image_count=image_count,
            images_without_alt=images_without_alt,
            internal_links=internal_links,
            external_links=external_links,
            word_count=word_count,
            main_text_excerpt=excerpt,
        )

    @staticmethod
    def _clean_visible_text(soup: BeautifulSoup) -> str:
        """Elimina nodos no relevantes y normaliza espacios del texto visible."""
        # Limpieza y transformación: se eliminan nodos no útiles antes de normalizar texto.
        for tag_name in ("script", "style", "noscript", "svg"):
            for tag in soup.find_all(tag_name):
                tag.decompose()

        raw_text = soup.get_text(separator=" ")
        compact_text = re.sub(r"\s+", " ", raw_text)
        return compact_text.strip()

    @staticmethod
    def _count_links(soup: BeautifulSoup, base_url: str) -> tuple[int, int]:
        """Cuenta enlaces internos/externos respecto al host base."""
        base_host = urlparse(base_url).netloc
        internal = 0
        external = 0

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            absolute_url = urljoin(base_url, href)
            target_host = urlparse(absolute_url).netloc
            if target_host == base_host:
                internal += 1
            else:
                external += 1
        return internal, external