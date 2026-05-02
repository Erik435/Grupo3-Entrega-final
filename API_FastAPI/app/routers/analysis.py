import json

from fastapi import APIRouter, Depends, status
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Analysis
from app.schemas import (
    AnalysisRequest,
    AnalysisResponse,
    HealthResponse,
    StatsResponse,
)
from app.services import MisinformationAnalyzer

router = APIRouter(tags=["analysis"])
analyzer = MisinformationAnalyzer()


def _to_response(model: Analysis) -> AnalysisResponse:
    return AnalysisResponse(
        id=model.id,
        credibility_score=model.credibility_score,
        risk_score=model.risk_score,
        risk_level=model.risk_level,
        flags=json.loads(model.flags_detected),
        explanation=model.explanation,
        created_at=model.created_at,
        category_scores=None,
        evidence=None,
        verdict=None,
        verification_summary=None,
        supporting_sources=None,
        external_check_summary=None,
        external_fact_checks=None,
        fact_check_direct=None,
        trusted_sources_count=None,
        semantic_confidence=None,
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post("/analyze", response_model=AnalysisResponse, status_code=status.HTTP_201_CREATED)
def analyze_news(payload: AnalysisRequest, db: Session = Depends(get_db)) -> AnalysisResponse:
    result = analyzer.analyze(payload)

    analysis = Analysis(
        title=payload.title,
        content=payload.content,
        link=payload.link,
        source=payload.source,
        author=payload.author,
        credibility_score=result.credibility_score,
        risk_score=result.risk_score,
        risk_level=result.risk_level,
        flags_detected=json.dumps(result.flags, ensure_ascii=False),
        explanation=result.explanation,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return AnalysisResponse(
        id=analysis.id,
        credibility_score=analysis.credibility_score,
        risk_score=analysis.risk_score,
        risk_level=analysis.risk_level,
        flags=result.flags,
        explanation=analysis.explanation,
        created_at=analysis.created_at,
        category_scores=result.category_scores,
        evidence=result.evidence,
        verdict=result.verdict,
        verification_summary=result.verification_summary,
        supporting_sources=result.supporting_sources,
        external_check_summary=result.external_check_summary,
        external_fact_checks=result.external_fact_checks,
        fact_check_direct=result.fact_check_direct,
        trusted_sources_count=result.trusted_sources_count,
        semantic_confidence=result.semantic_confidence,
    )


@router.get("/history", response_model=list[AnalysisResponse])
def get_history(db: Session = Depends(get_db)) -> list[AnalysisResponse]:
    query = select(Analysis).order_by(desc(Analysis.created_at))
    analyses = db.scalars(query).all()
    return [_to_response(item) for item in analyses]


@router.get("/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)) -> StatsResponse:
    stmt = select(
        func.count(Analysis.id),
        func.sum(case((Analysis.risk_level == "bajo", 1), else_=0)),
        func.sum(case((Analysis.risk_level == "medio", 1), else_=0)),
        func.sum(case((Analysis.risk_level == "alto", 1), else_=0)),
        func.avg(Analysis.risk_score),
        func.avg(Analysis.credibility_score),
    )
    (
        total_analyzed,
        low_risk_count,
        medium_risk_count,
        high_risk_count,
        average_risk_score,
        average_credibility_score,
    ) = db.execute(stmt).one()

    return StatsResponse(
        total_analyzed=total_analyzed or 0,
        low_risk_count=low_risk_count or 0,
        medium_risk_count=medium_risk_count or 0,
        high_risk_count=high_risk_count or 0,
        average_risk_score=round(float(average_risk_score or 0), 2),
        average_credibility_score=round(float(average_credibility_score or 0), 2),
    )
