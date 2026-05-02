#
"""Integración opcional con Gemini para enriquecer el análisis base."""

import json
import os
import re
from typing import Optional

import httpx

from app.schemas.analysis import AIInsights
from app.utils.logger import get_logger

logger = get_logger("ai")


class AIEnricher:
    """Solicita clasificación y resumen semántico a un modelo externo."""

    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.api_url = os.getenv(
            "GEMINI_API_URL",
            "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        )
        self.model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

    def enrich(
        self,
        url: str,
        title: str,
        meta_description: str,
        excerpt: str,
    ) -> Optional[AIInsights]:
        """Devuelve insights de IA si hay credenciales y respuesta válida."""
        # Integración opcional con IA: si no hay API key, el análisis base sigue funcionando.
        if not self.api_key:
            return None

        prompt = (
            "Analiza los siguientes datos del sitio web y responde SOLO JSON válido con "
            "las claves: site_type, main_topic, short_summary, semantic_recommendations "
            "(lista de máximo 4 recomendaciones cortas).\n\n"
            f"url: {url}\n"
            f"title: {title}\n"
            f"meta_description: {meta_description}\n"
            f"excerpt: {excerpt}\n"
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "Eres un analista de contenido web. "
                                "Responde solo JSON valido sin markdown.\n\n"
                                f"{prompt}"
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.2},
        }
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": self.api_key,
        }

        try:
            request_url = self.api_url.format(model=self.model)
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    request_url,
                    json=payload,
                    headers=headers,
                )
            response.raise_for_status()
            content = (
                response.json()
                .get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            data = self._safe_json_parse(content)
            return AIInsights(
                site_type=data.get("site_type"),
                main_topic=data.get("main_topic"),
                short_summary=data.get("short_summary"),
                semantic_recommendations=data.get("semantic_recommendations", []),
                provider="gemini",
            )
        except Exception:
            logger.warning("No fue posible enriquecer con IA para %s", url, exc_info=True)
            return None

    @staticmethod
    def _safe_json_parse(raw_text: str) -> dict:
        """Intenta parsear JSON directo o extraer bloque JSON embebido."""
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", raw_text)
            if not match:
                raise
            return json.loads(match.group(0))