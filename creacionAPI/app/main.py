#Grupo3#
#Dev Erik
"""Punto de entrada de la API y definición de endpoints HTTP."""

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, status

from app.schemas.analysis import (
    AnalyzeSiteRequest,
    CompareSitesRequest,
    CompareSitesResponse,
    HealthResponse,
    SiteAnalysisResponse,
)
from app.services.analyzer import SiteAnalyzer
from app.utils.logger import get_logger

app = FastAPI(
    title="Web Insight API",
    version="1.0.0",
    description="API REST para analizar sitios web y comparar su calidad técnica y de contenido.",
)

logger = get_logger("api")
analyzer = SiteAnalyzer()


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Devuelve estado operativo y timestamp en zona UTC-5."""
    utc_minus_5 = timezone(timedelta(hours=-5))
    timestamp = datetime.now(utc_minus_5).isoformat()
    return HealthResponse(status="Api Funcionando - Grupo3", timestamp=timestamp)


@app.post("/analyze-site", response_model=SiteAnalysisResponse)
def analyze_site(payload: AnalyzeSiteRequest) -> SiteAnalysisResponse:
    """Ejecuta el análisis completo de una URL y devuelve métricas + scores."""
    # Endpoint principal para ejecutar extracción, limpieza, métricas y scoring.
    try:
        return analyzer.analyze_site(str(payload.url))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Error inesperado al analizar %s", payload.url)
        # Manejo de errores para mantener respuestas consistentes ante fallos no controlados.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo completar el análisis del sitio.",
        ) from exc


@app.post("/compare-sites", response_model=CompareSitesResponse)
def compare_sites(payload: CompareSitesRequest) -> CompareSitesResponse:
    """Compara múltiples URLs analizadas y construye ranking global."""
    # Comparación de varios sitios con ranking y observaciones agregadas.
    try:
        return analyzer.compare_sites([str(url) for url in payload.urls])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Error inesperado al comparar sitios")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo completar la comparación de sitios.",
        ) from exc