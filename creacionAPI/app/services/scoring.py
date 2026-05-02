#
"""Reglas de puntuación e interpretación de calidad de sitio web."""

from app.schemas.analysis import Scores
from app.services.text_processing import ExtractedData


class ScoreCalculator:
    """Calcula scores y genera issues/recommendations accionables."""

    @staticmethod
    def calculate(
        url: str,
        status_code: int,
        data: ExtractedData,
    ) -> tuple[Scores, list[str], list[str]]:
        """Evalúa métricas contra umbrales y produce puntuación final."""
        issues: list[str] = []
        recommendations: list[str] = []

        # Cálculo de scores con reglas explícitas y trazables.
        seo_score = 100.0
        if not data.title:
            seo_score -= 20
            issues.append("Falta el título de la página.")
            recommendations.append("Define un <title> descriptivo y único.")
        elif len(data.title) < 15 or len(data.title) > 70:
            seo_score -= 8
            issues.append("El título no está en un rango recomendado (15-70 caracteres).")
            recommendations.append("Ajusta la longitud del título para mejorar SEO.")

        if not data.meta_description:
            seo_score -= 18
            issues.append("Falta la meta descripción.")
            recommendations.append("Incluye una meta descripción de 120-160 caracteres.")
        elif len(data.meta_description) < 50 or len(data.meta_description) > 180:
            seo_score -= 7
            issues.append("La meta descripción no está en un rango recomendado.")
            recommendations.append("Ajusta la meta descripción entre 50 y 180 caracteres.")

        if data.h1_count == 0:
            seo_score -= 10
            issues.append("No hay etiquetas H1.")
            recommendations.append("Incluye un H1 principal para estructurar el contenido.")
        elif data.h1_count > 1:
            seo_score -= 6
            issues.append("Hay múltiples H1, lo que puede diluir la jerarquía.")
            recommendations.append("Mantén un único H1 principal por página.")

        if status_code >= 400:
            seo_score -= 25
            issues.append(f"El sitio devolvió un estado HTTP problemático: {status_code}.")
            recommendations.append("Verifica disponibilidad y códigos de respuesta HTTP.")

        accessibility_score = 100.0
        if data.image_count > 0:
            missing_alt_ratio = data.images_without_alt / data.image_count
            accessibility_score -= round(missing_alt_ratio * 40, 2)
            if data.images_without_alt > 0:
                issues.append("Hay imágenes sin atributo alt.")
                recommendations.append("Añade textos alternativos a las imágenes.")
        else:
            accessibility_score -= 5
            issues.append("No se detectaron imágenes; revisa si el contenido visual es suficiente.")

        if data.h2_count == 0:
            accessibility_score -= 8
            issues.append("No hay subtítulos H2 para segmentar el contenido.")
            recommendations.append("Usa encabezados H2 para mejorar legibilidad.")

        content_quality_score = 100.0
        if data.word_count < 300:
            content_quality_score -= 22
            issues.append("El contenido textual parece escaso (<300 palabras).")
            recommendations.append("Amplía el contenido útil para el usuario.")
        elif data.word_count > 2500:
            content_quality_score -= 6
            issues.append("El contenido es muy extenso; podría afectar escaneabilidad.")
            recommendations.append("Divide el contenido en secciones más cortas y claras.")

        if data.internal_links < 3:
            content_quality_score -= 10
            issues.append("Poca interconexión interna entre contenidos.")
            recommendations.append("Añade enlaces internos hacia páginas relevantes.")

        if not url.startswith("https://"):
            content_quality_score -= 12
            issues.append("El sitio no usa HTTPS.")
            recommendations.append("Habilita HTTPS para seguridad y confianza.")

        seo_score = max(0.0, round(seo_score, 2))
        accessibility_score = max(0.0, round(accessibility_score, 2))
        content_quality_score = max(0.0, round(content_quality_score, 2))
        overall_score = round(
            seo_score * 0.4 + accessibility_score * 0.25 + content_quality_score * 0.35,
            2,
        )

        scores = Scores(
            seo_score=seo_score,
            accessibility_score=accessibility_score,
            content_quality_score=content_quality_score,
            overall_score=overall_score,
        )
        return scores, issues, recommendations