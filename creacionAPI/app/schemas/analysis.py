"""Esquemas Pydantic de entrada/salida para la API de análisis web."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class HealthResponse(BaseModel):
    status: str
    timestamp: str


class AnalyzeSiteRequest(BaseModel):
    url: HttpUrl


class CompareSitesRequest(BaseModel):
    urls: list[HttpUrl] = Field(min_length=2, max_length=10)


class Scores(BaseModel):
    seo_score: float = Field(ge=0, le=100)
    accessibility_score: float = Field(ge=0, le=100)
    content_quality_score: float = Field(ge=0, le=100)
    overall_score: float = Field(ge=0, le=100)


class AIInsights(BaseModel):
    site_type: Optional[str] = None
    main_topic: Optional[str] = None
    short_summary: Optional[str] = None
    semantic_recommendations: list[str] = Field(default_factory=list)
    provider: Optional[str] = None


class SiteAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    status_code: int
    response_time_ms: float
    has_https: bool
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
    scores: Scores
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    ai_insights: Optional[AIInsights] = None


class RankingEntry(BaseModel):
    url: str
    overall_score: float


class CompareSitesResponse(BaseModel):
    results: list[SiteAnalysisResponse]
    ranking: list[RankingEntry]
    comparative_observations: list[str] = Field(default_factory=list)