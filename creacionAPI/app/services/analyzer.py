"""Orquestación del flujo de análisis y comparación entre sitios."""

from app.schemas.analysis import CompareSitesResponse, RankingEntry, SiteAnalysisResponse
from app.services.ai_enrichment import AIEnricher
from app.services.scoring import ScoreCalculator
from app.services.text_processing import TextProcessor
from app.services.web_scraper import SiteFetchError, WebScraper
from app.utils.logger import get_logger

logger = get_logger("analyzer")


class SiteAnalyzer:
    """Coordina scraping, procesamiento de texto, scoring e IA opcional."""

    def __init__(self) -> None:
        self.scraper = WebScraper()
        self.ai_enricher = AIEnricher()

    def analyze_site(self, url: str) -> SiteAnalysisResponse:
        """Analiza una URL individual y devuelve una respuesta estructurada."""
        if not url:
            raise ValueError("La URL es obligatoria.")

        try:
            fetch_result = self.scraper.fetch(url)
        except SiteFetchError as exc:
            logger.warning("Fallo de extracción en %s: %s", url, exc)
            return self._build_failed_analysis(url=url, reason=str(exc))

        metrics = TextProcessor.extract_metrics(fetch_result.html, fetch_result.url)
        scores, issues, recommendations = ScoreCalculator.calculate(
            url=fetch_result.url,
            status_code=fetch_result.status_code,
            data=metrics,
        )
        ai_insights = self.ai_enricher.enrich(
            url=fetch_result.url,
            title=metrics.title,
            meta_description=metrics.meta_description,
            excerpt=metrics.main_text_excerpt,
        )

        return SiteAnalysisResponse(
            url=fetch_result.url,
            status_code=fetch_result.status_code,
            response_time_ms=fetch_result.response_time_ms,
            has_https=fetch_result.url.startswith("https://"),
            title=metrics.title,
            meta_description=metrics.meta_description,
            h1_count=metrics.h1_count,
            h2_count=metrics.h2_count,
            image_count=metrics.image_count,
            images_without_alt=metrics.images_without_alt,
            internal_links=metrics.internal_links,
            external_links=metrics.external_links,
            word_count=metrics.word_count,
            main_text_excerpt=metrics.main_text_excerpt,
            scores=scores,
            issues=sorted(set(issues)),
            recommendations=sorted(set(recommendations)),
            ai_insights=ai_insights,
        )

    def compare_sites(self, urls: list[str]) -> CompareSitesResponse:
        """Compara varias URLs y genera ranking y observaciones agregadas."""
        if len(urls) < 2:
            raise ValueError("Se necesitan al menos 2 URLs para comparar.")

        results = [self.analyze_site(url) for url in urls]
        ranking = sorted(
            [RankingEntry(url=item.url, overall_score=item.scores.overall_score) for item in results],
            key=lambda entry: entry.overall_score,
            reverse=True,
        )
        observations = self._build_comparative_observations(results, ranking)
        return CompareSitesResponse(
            results=results,
            ranking=ranking,
            comparative_observations=observations,
        )

    @staticmethod
    def _build_comparative_observations(
        results: list[SiteAnalysisResponse],
        ranking: list[RankingEntry],
    ) -> list[str]:
        """Resume diferencias clave entre sitios para lectura rápida."""
        # Comparación de sitios con observaciones prácticas para interpretar resultados.
        if not results:
            return ["No hay resultados para comparar."]

        best = ranking[0]
        worst = ranking[-1]
        avg_word_count = round(sum(item.word_count for item in results) / len(results), 2)
        avg_response = round(sum(item.response_time_ms for item in results) / len(results), 2)

        observations = [
            f"El sitio con mayor score general es {best.url} ({best.overall_score}).",
            f"El sitio con menor score general es {worst.url} ({worst.overall_score}).",
            f"Promedio de palabras analizadas por sitio: {avg_word_count}.",
            f"Promedio de tiempo de respuesta: {avg_response} ms.",
        ]

        https_count = sum(1 for item in results if item.has_https)
        if https_count < len(results):
            observations.append(
                "No todos los sitios usan HTTPS; hay margen de mejora en seguridad."
            )
        return observations

    @staticmethod
    def _build_failed_analysis(url: str, reason: str) -> SiteAnalysisResponse:
        """Construye una respuesta consistente cuando el scraping falla."""
        return SiteAnalysisResponse(
            url=url,
            status_code=0,
            response_time_ms=0,
            has_https=url.startswith("https://"),
            title="",
            meta_description="",
            h1_count=0,
            h2_count=0,
            image_count=0,
            images_without_alt=0,
            internal_links=0,
            external_links=0,
            word_count=0,
            main_text_excerpt="",
            scores={
                "seo_score": 0,
                "accessibility_score": 0,
                "content_quality_score": 0,
                "overall_score": 0,
            },
            issues=[f"No fue posible analizar el sitio: {reason}"],
            recommendations=["Revisa la URL, conectividad o restricciones del servidor."],
            ai_insights=None,
        )