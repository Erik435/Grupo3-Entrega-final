from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnalysisRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    content: str | None = None
    link: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=200)
    author: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_minimum_content(self) -> "AnalysisRequest":
        useful_fields = [self.title, self.content, self.link]
        if not any(value and value.strip() for value in useful_fields):
            raise ValueError(
                "Debe enviarse al menos uno de estos campos con contenido: "
                "title, content o link."
            )
        return self


class AnalysisResultData(BaseModel):
    credibility_score: int = Field(ge=0, le=100)
    risk_score: int = Field(ge=0, le=100)
    risk_level: Literal["bajo", "medio", "alto"]
    flags: list[str]
    explanation: str
    category_scores: dict[str, int] | None = None
    evidence: list[str] | None = None
    verdict: str | None = None
    verification_summary: str | None = None
    supporting_sources: list[str] | None = None
    external_check_summary: str | None = None
    external_fact_checks: list[dict[str, str]] | None = None
    fact_check_direct: bool | None = None
    trusted_sources_count: int | None = None
    semantic_confidence: float | None = None


class AnalysisResponse(AnalysisResultData):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class HealthResponse(BaseModel):
    status: Literal["ok"]


class StatsResponse(BaseModel):
    total_analyzed: int
    low_risk_count: int
    medium_risk_count: int
    high_risk_count: int
    average_risk_score: float
    average_credibility_score: float
