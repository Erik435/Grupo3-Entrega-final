from dataclasses import dataclass
from pathlib import Path
import json
import logging
import os
import re
from html import unescape
import unicodedata
import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

import yaml

from app.schemas.analysis import AnalysisRequest

logger = logging.getLogger(__name__)


@dataclass
class AnalyzerResult:
    credibility_score: int
    risk_score: int
    risk_level: str
    flags: list[str]
    explanation: str
    category_scores: dict[str, int]
    evidence: list[str]
    verdict: str
    verification_summary: str
    supporting_sources: list[str]
    external_check_summary: str
    external_fact_checks: list[dict[str, str]]
    fact_check_direct: bool
    trusted_sources_count: int
    semantic_confidence: float


class MisinformationAnalyzer:
    SENSATIONAL_PHRASES = [
        "urgente",
        "impactante",
        "ultima hora",
        "última hora",
        "milagroso",
        "secreto",
    ]
    WEB_TIMEOUT_SECONDS = 4
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    DEFAULT_CONFIG = {
        "model_name": "Heuristic Risk Model",
        "model_version": "2.0.0",
        "thresholds": {"low_max": 39, "medium_max": 69},
        "weights": {},
        "categories": {},
        "trusted_sources": [],
    }

    def __init__(self, config_path: str = "config/rules.yaml") -> None:
        self.config = self._load_config(config_path)
        self.weights: dict[str, int] = self.config.get("weights", {})
        self.thresholds: dict[str, int] = self.config.get("thresholds", {})
        self.categories: dict[str, list[str]] = self.config.get("categories", {})
        self.trusted_sources: list[str] = self.config.get("trusted_sources", [])
    CONSPIRACY_PHRASES = [
        "no quieren que lo sepas",
        "te estan mintiendo",
        "te están mintiendo",
        "los medios ocultan esto",
        "ocultado por",
    ]
    SHARING_CALLS = [
        "compartelo",
        "compártelo",
        "difundelo",
        "difúndelo",
        "antes de que lo borren",
    ]
    ABSOLUTE_CLAIMS = [
        "100% garantizado",
        "cura definitiva",
        "siempre funciona",
        "sin ninguna duda",
    ]
    URGENCY_PHRASES = [
        "ahora mismo",
        "inmediatamente",
        "no esperes",
        "antes de que sea tarde",
    ]
    SUSPICIOUS_DOMAINS = [
        ".xyz",
        ".top",
        ".click",
        ".buzz",
        ".monster",
        "blogspot",
        "weebly",
        "wixsite",
    ]
    SPANISH_STOPWORDS = {
        "de",
        "la",
        "el",
        "en",
        "y",
        "a",
        "los",
        "las",
        "un",
        "una",
        "para",
        "con",
        "por",
        "del",
        "que",
        "se",
        "es",
        "al",
        "lo",
        "como",
        "mas",
        "más",
    }

    def analyze(self, payload: AnalysisRequest) -> AnalyzerResult:
        risk_score = 0
        flags: list[str] = []
        category_scores = {"text_signals": 0, "metadata_signals": 0, "web_signals": 0}
        evidence: list[str] = []

        text = " ".join(
            value for value in [payload.title, payload.content] if value and value.strip()
        )
        text_lower = text.lower().strip()

        if text:
            risk_score, flags, text_points, text_evidence = self._analyze_text(
                text, text_lower, risk_score, flags
            )
            category_scores["text_signals"] += text_points
            evidence.extend(text_evidence)
        else:
            risk_score += self._weight("short_content", 8)
            flags.append("contenido textual insuficiente para evaluar contexto")
            category_scores["text_signals"] += self._weight("short_content", 8)

        risk_score, flags, metadata_points, metadata_evidence = self._analyze_metadata(
            payload, risk_score, flags
        )
        category_scores["metadata_signals"] += metadata_points
        evidence.extend(metadata_evidence)

        risk_score, flags, web_points, web_evidence = self._analyze_web_evidence(
            payload, risk_score, flags
        )
        category_scores["web_signals"] += web_points
        evidence.extend(web_evidence)

        corroboration = self._corroborate_with_news_sources(payload)
        if corroboration["status"] == "supported":
            bonus = self._weight("multi_source_support_bonus", 15)
            risk_score = max(0, risk_score - bonus)
            evidence.append("multi_source_support")
        elif corroboration["status"] == "weak":
            penalty = self._weight("weak_corroboration_penalty", 10)
            risk_score += penalty
            flags.append("poca corroboración en fuentes externas")
            evidence.append("weak_external_corroboration")

        external_check = self._query_google_fact_check(payload)
        if external_check["status"] == "configured":
            if external_check["false_hits"] > 0:
                penalty = self._weight("fact_check_false_penalty", 20)
                risk_score += penalty
                flags.append("verificaciones externas reportan contenido cuestionado")
                evidence.append("fact_check_false_hits")
            elif external_check["true_hits"] > 0:
                bonus = self._weight("fact_check_true_bonus", 15)
                risk_score = max(0, risk_score - bonus)
                evidence.append("fact_check_true_hits")

        if external_check["false_hits"] > 0:
            strong_floor = self._weight("fact_check_false_risk_floor", 82)
            per_hit_boost = min(external_check["false_hits"] * 3, 12)
            risk_score = max(risk_score, strong_floor + per_hit_boost)

        if external_check["true_hits"] == 0 and external_check["false_hits"] == 0:
            risk_score = max(risk_score, self._weight("no_factcheck_risk_floor", 28))

        risk_score = max(0, min(100, risk_score))
        credibility_score = 100 - risk_score
        risk_level = self._risk_level_from_score(risk_score)
        explanation = self._build_explanation(risk_level, flags)
        verdict = self._build_verdict(
            risk_score=risk_score,
            corroboration_status=corroboration["status"],
            trusted_hits=corroboration["trusted_hits"],
            true_hits=external_check["true_hits"],
            false_hits=external_check["false_hits"],
        )

        return AnalyzerResult(
            credibility_score=credibility_score,
            risk_score=risk_score,
            risk_level=risk_level,
            flags=flags,
            explanation=explanation,
            category_scores=category_scores,
            evidence=evidence,
            verdict=verdict,
            verification_summary=corroboration["summary"],
            supporting_sources=corroboration["sources"],
            external_check_summary=external_check["summary"],
            external_fact_checks=external_check["matches"],
            fact_check_direct=external_check["true_hits"] > 0 or external_check["false_hits"] > 0,
            trusted_sources_count=corroboration["trusted_hits"],
            semantic_confidence=float(corroboration.get("semantic_confidence", 0)),
        )

    def _analyze_text(
        self, text: str, text_lower: str, risk_score: int, flags: list[str]
    ) -> tuple[int, list[str], int, list[str]]:
        points = 0
        evidence: list[str] = []
        words = text.split()
        uppercase_words = [word for word in words if len(word) > 3 and word.isupper()]
        uppercase_ratio = (len(uppercase_words) / len(words)) if words else 0
        if uppercase_ratio >= 0.2:
            weight = self._weight("uppercase_excess", 10)
            risk_score += weight
            points += weight
            flags.append("uso excesivo de mayúsculas")
            evidence.append("ratio_alta_mayusculas")

        exclamation_count = text.count("!")
        if exclamation_count >= 3:
            weight = self._weight("exclamation_excess", 8)
            risk_score += weight
            points += weight
            flags.append("exceso de signos de exclamación")
            evidence.append("signos_exclamacion_excesivos")

        risk_score, delta = self._add_phrase_risk(
            text_lower,
            self.SENSATIONAL_PHRASES,
            self._weight("sensational_phrase", 8),
            "uso de lenguaje sensacionalista",
            risk_score,
            flags,
        )
        points += delta
        if delta:
            evidence.append("frases_sensacionalistas")
        risk_score, delta = self._add_phrase_risk(
            text_lower,
            self.CONSPIRACY_PHRASES,
            self._weight("conspiracy_phrase", 14),
            "frases conspirativas",
            risk_score,
            flags,
        )
        points += delta
        if delta:
            evidence.append("frases_conspirativas")
        risk_score, delta = self._add_phrase_risk(
            text_lower,
            self.SHARING_CALLS,
            self._weight("share_call", 12),
            "llamado emocional a compartir",
            risk_score,
            flags,
        )
        points += delta
        if delta:
            evidence.append("llamado_compartir")
        risk_score, delta = self._add_phrase_risk(
            text_lower,
            self.ABSOLUTE_CLAIMS,
            self._weight("absolute_claim", 10),
            "afirmaciones absolutas sin contexto",
            risk_score,
            flags,
        )
        points += delta
        if delta:
            evidence.append("afirmaciones_absolutas")
        risk_score, delta = self._add_phrase_risk(
            text_lower,
            self.URGENCY_PHRASES,
            self._weight("urgency_phrase", 9),
            "frases de urgencia extrema",
            risk_score,
            flags,
        )
        points += delta
        if delta:
            evidence.append("frases_urgencia")
        if len(text) < 80:
            weight = self._weight("short_content", 8)
            risk_score += weight
            points += weight
            flags.append("contenido demasiado corto o poco informativo")
            evidence.append("contenido_breve")

        emotional_keywords = ["escandalo", "escándalo", "terror", "catastrofe", "catástrofe"]
        if any(keyword in text_lower for keyword in emotional_keywords):
            weight = self._weight("emotional_alarmist", 8)
            risk_score += weight
            points += weight
            flags.append("lenguaje emocional o alarmista")
            evidence.append("lenguaje_alarmista")

        return risk_score, flags, points, evidence

    def _analyze_metadata(
        self, payload: AnalysisRequest, risk_score: int, flags: list[str]
    ) -> tuple[int, list[str], int, list[str]]:
        points = 0
        evidence: list[str] = []
        source = (payload.source or "").strip().lower()
        author = (payload.author or "").strip().lower()
        link = (payload.link or "").strip()

        if author and author in {"anonimo", "anónimo", "desconocido"}:
            weight = self._weight("author_anonymous", 10)
            risk_score += weight
            points += weight
            flags.append("autor anónimo o no verificable")
            evidence.append("author_unverified")

        if link:
            parsed = urlparse(link)
            host = (parsed.netloc or "").lower()
            if parsed.scheme != "https":
                weight = self._weight("link_no_https", 8)
                risk_score += weight
                points += weight
                flags.append("enlace sin https")
                evidence.append("link_http")
            if not host:
                weight = self._weight("link_invalid", 10)
                risk_score += weight
                points += weight
                flags.append("enlace inválido o sospechoso")
                evidence.append("link_invalid")
            elif any(token in host for token in self.SUSPICIOUS_DOMAINS):
                weight = self._weight("suspicious_domain", 12)
                risk_score += weight
                points += weight
                flags.append("dominio raro o poco confiable")
                evidence.append("domain_suspicious")
            if source and host and source not in host:
                weight = self._weight("source_link_mismatch", 6)
                risk_score += weight
                points += weight
                flags.append("fuente inconsistente con el enlace")
                evidence.append("source_link_mismatch")

        return risk_score, flags, points, evidence

    def _analyze_web_evidence(
        self, payload: AnalysisRequest, risk_score: int, flags: list[str]
    ) -> tuple[int, list[str], int, list[str]]:
        points = 0
        evidence: list[str] = []
        link = (payload.link or "").strip()
        if not link:
            return risk_score, flags, points, evidence

        parsed = urlparse(link)
        if not parsed.netloc:
            return risk_score, flags, points, evidence

        try:
            request = Request(
                link,
                headers={
                    "User-Agent": self.USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            with urlopen(request, timeout=self.WEB_TIMEOUT_SECONDS) as response:
                final_url = response.geturl()
                content_type = (response.headers.get("Content-Type") or "").lower()
                html_content = response.read(8192).decode("utf-8", errors="ignore")
        except HTTPError as exc:
            if exc.code >= 500:
                risk_score += 6
                flags.append("fuente temporalmente inestable (error 5xx)")
            elif exc.code in {403, 404, 410}:
                risk_score += 12
                flags.append("enlace no accesible o removido")
            else:
                risk_score += 8
                flags.append("respuesta web irregular para el enlace")
            points += 8
            evidence.append("web_http_error")
            return risk_score, flags, points, evidence
        except URLError:
            weight = self._weight("link_unreachable", 10)
            risk_score += weight
            points += weight
            flags.append("no se pudo verificar el enlace en la web")
            evidence.append("web_unreachable")
            return risk_score, flags, points, evidence
        except TimeoutError:
            risk_score += 7
            points += 7
            flags.append("enlace con tiempo de respuesta alto o no disponible")
            evidence.append("web_timeout")
            return risk_score, flags, points, evidence

        final_host = (urlparse(final_url).netloc or "").lower()
        original_host = (parsed.netloc or "").lower()
        if final_host and original_host and final_host != original_host:
            weight = self._weight("link_redirect_domain", 8)
            risk_score += weight
            points += weight
            flags.append("el enlace redirige a un dominio distinto")
            evidence.append("web_redirect_other_domain")

        if "text/html" not in content_type:
            weight = self._weight("link_not_html", 5)
            risk_score += weight
            points += weight
            flags.append("el enlace no parece una pagina informativa HTML")
            evidence.append("web_non_html")

        page_title = self._extract_html_title(html_content)
        submitted_title = (payload.title or "").strip()
        if page_title and submitted_title:
            overlap = self._title_overlap_ratio(submitted_title, page_title)
            if overlap < 0.2:
                weight = self._weight("title_link_mismatch", 9)
                risk_score += weight
                points += weight
                flags.append("baja consistencia entre titulo enviado y pagina enlazada")
                evidence.append("title_page_mismatch")

        if not page_title:
            weight = self._weight("page_without_title", 4)
            risk_score += weight
            points += weight
            flags.append("la pagina enlazada no expone titulo verificable")
            evidence.append("page_missing_title")

        return risk_score, flags, points, evidence

    @staticmethod
    def _extract_html_title(html_content: str) -> str:
        match = re.search(r"<title[^>]*>(.*?)</title>", html_content, flags=re.I | re.S)
        if not match:
            return ""
        cleaned = re.sub(r"\s+", " ", unescape(match.group(1))).strip()
        return cleaned[:300]

    @staticmethod
    def _title_overlap_ratio(left: str, right: str) -> float:
        left_tokens = {token for token in re.findall(r"\w+", left.lower()) if len(token) > 2}
        right_tokens = {token for token in re.findall(r"\w+", right.lower()) if len(token) > 2}
        if not left_tokens or not right_tokens:
            return 0.0
        common = left_tokens.intersection(right_tokens)
        return len(common) / max(len(left_tokens), 1)

    @staticmethod
    def _add_phrase_risk(
        text_lower: str,
        phrases: list[str],
        points: int,
        flag: str,
        risk_score: int,
        flags: list[str],
    ) -> tuple[int, int]:
        if any(phrase in text_lower for phrase in phrases):
            risk_score += points
            flags.append(flag)
            return risk_score, points
        return risk_score, 0

    def _risk_level_from_score(self, risk_score: int) -> str:
        medium_max = self.thresholds.get("medium_max", 69)
        low_max = self.thresholds.get("low_max", 39)
        if risk_score > medium_max:
            return "alto"
        if risk_score > low_max:
            return "medio"
        return "bajo"

    @staticmethod
    def _build_explanation(risk_level: str, flags: list[str]) -> str:
        if not flags:
            return (
                "No se detectaron señales críticas de desinformación con las reglas "
                "heurísticas definidas."
            )
        top_flags = ", ".join(flags[:3])
        return (
            f"El contenido se clasifica con riesgo {risk_level} por señales como: "
            f"{top_flags}. Este resultado es orientativo y no representa una verdad absoluta."
        )

    def get_model_info(self) -> dict:
        return {
            "model_name": self.config.get("model_name", "Heuristic Risk Model"),
            "model_version": self.config.get("model_version", "2.0.0"),
            "thresholds": self.thresholds,
            "weights": self.weights,
            "categories": self.categories,
        }

    def _load_config(self, config_path: str) -> dict:
        path = Path(config_path)
        if not path.exists():
            return self.DEFAULT_CONFIG.copy()
        with path.open("r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file) or {}
        merged = self.DEFAULT_CONFIG.copy()
        merged.update(loaded)
        merged["thresholds"] = {**self.DEFAULT_CONFIG["thresholds"], **loaded.get("thresholds", {})}
        merged["weights"] = {**self.DEFAULT_CONFIG["weights"], **loaded.get("weights", {})}
        merged["categories"] = {**self.DEFAULT_CONFIG["categories"], **loaded.get("categories", {})}
        return merged

    def _weight(self, key: str, fallback: int) -> int:
        value = self.weights.get(key, fallback)
        return int(value)

    def _corroborate_with_news_sources(self, payload: AnalysisRequest) -> dict:
        query = self._build_search_query(payload)
        if not query:
            return {
                "status": "unknown",
                "summary": "No hay suficiente contexto para contrastar en fuentes externas.",
                "sources": [],
                "trusted_hits": 0,
            }

        search_url = (
            "https://news.google.com/rss/search?q="
            f"{quote_plus(query)}&hl=es-419&gl=US&ceid=US:es-419"
        )
        try:
            request = Request(
                search_url,
                headers={"User-Agent": self.USER_AGENT, "Accept": "application/rss+xml"},
            )
            with urlopen(request, timeout=self.WEB_TIMEOUT_SECONDS) as response:
                rss_text = response.read().decode("utf-8", errors="ignore")
        except Exception:
            return {
                "status": "unknown",
                "summary": (
                    "No se pudo completar la búsqueda externa en este momento. "
                    "El resultado se basa en análisis heurístico local."
                ),
                "sources": [],
                "trusted_hits": 0,
            }

        try:
            root = ET.fromstring(rss_text)
        except ET.ParseError:
            return {
                "status": "unknown",
                "summary": "La respuesta de búsqueda externa no fue válida para corroboración.",
                "sources": [],
                "trusted_hits": 0,
            }

        source_names: list[str] = []
        matched_items = 0
        query_tokens = self._meaningful_tokens(query)
        for item in root.findall(".//item")[:12]:
            source_text = (item.findtext("source") or "").strip()
            title_text = (item.findtext("title") or "").strip()
            if source_text and self._token_overlap_ratio(query_tokens, title_text) >= 0.28:
                source_names.append(source_text)
                matched_items += 1

        unique_sources = sorted({name for name in source_names if name})
        normalized_trusted = [self._normalize_text(token) for token in self.trusted_sources]
        trusted_hits = sum(
            1
            for source in unique_sources
            if any(token in self._normalize_text(source) for token in normalized_trusted)
        )

        semantic_confidence = round(min(1.0, matched_items / max(1, 6)), 2)

        if len(unique_sources) >= 3 and trusted_hits >= 2 and matched_items >= 3:
            return {
                "status": "supported",
                "summary": (
                    f"Varias fuentes independientes confirman la temática ({len(unique_sources)} "
                    f"fuentes detectadas, {trusted_hits} de alta confiabilidad, "
                    f"{matched_items} titulares coincidentes)."
                ),
                "sources": unique_sources[:6],
                "trusted_hits": trusted_hits,
                "semantic_confidence": semantic_confidence,
            }
        if len(unique_sources) <= 1 or matched_items <= 1:
            return {
                "status": "weak",
                "summary": (
                    "No se encontró corroboración amplia en fuentes externas; "
                    "la afirmación requiere mayor verificación."
                ),
                "sources": unique_sources[:6],
                "trusted_hits": trusted_hits,
                "semantic_confidence": semantic_confidence,
            }

        return {
            "status": "unknown",
            "summary": (
                f"Se hallaron {len(unique_sources)} fuentes y {matched_items} titulares con "
                "coincidencia parcial."
            ),
            "sources": unique_sources[:6],
            "trusted_hits": trusted_hits,
            "semantic_confidence": semantic_confidence,
        }

    @staticmethod
    def _build_search_query(payload: AnalysisRequest) -> str:
        if payload.title and payload.title.strip():
            return payload.title.strip()[:180]
        if payload.content and payload.content.strip():
            words = payload.content.strip().split()
            return " ".join(words[:16])
        return ""

    @staticmethod
    def _build_verdict(
        risk_score: int,
        corroboration_status: str,
        trusted_hits: int,
        true_hits: int,
        false_hits: int,
    ) -> str:
        if false_hits > 0:
            return "Probablemente falso: existen verificaciones externas con calificación negativa."
        if true_hits > 0 and risk_score <= 45:
            return "Probablemente cierto: hay verificaciones externas con calificación positiva."
        if true_hits == 0 and corroboration_status == "supported" and trusted_hits >= 2:
            return (
                "Corroboración parcial: hay coincidencia en medios confiables, "
                "pero no existe fact-check positivo directo."
            )
        if corroboration_status == "weak" or risk_score >= 70:
            return "Probablemente falso o no verificado por falta de corroboración sólida."
        return (
            "Sin evidencia concluyente: se requiere fact-check directo o mayor "
            "validación de fuentes."
        )

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        return "".join(char for char in normalized if not unicodedata.combining(char)).lower()

    def _meaningful_tokens(self, text: str) -> set[str]:
        normalized = self._normalize_text(text)
        tokens = set(re.findall(r"\w+", normalized))
        return {token for token in tokens if len(token) > 2 and token not in self.SPANISH_STOPWORDS}

    def _token_overlap_ratio(self, query_tokens: set[str], candidate_text: str) -> float:
        if not query_tokens:
            return 0.0
        candidate_tokens = self._meaningful_tokens(candidate_text)
        if not candidate_tokens:
            return 0.0
        overlap = query_tokens.intersection(candidate_tokens)
        return len(overlap) / max(len(query_tokens), 1)

    def _query_google_fact_check(self, payload: AnalysisRequest) -> dict:
        api_key = os.getenv("FACT_CHECK_API_KEY", "").strip()
        query = self._build_search_query(payload)
        if not api_key:
            logger.info(
                "Google Fact Check no configurado: FACT_CHECK_API_KEY ausente. "
                "Se omite llamada externa."
            )
            return {
                "status": "not_configured",
                "summary": "Integración externa no configurada (FACT_CHECK_API_KEY).",
                "matches": [],
                "true_hits": 0,
                "false_hits": 0,
            }
        if not query:
            logger.info(
                "Google Fact Check omitido: no hay query suficiente para buscar."
            )
            return {
                "status": "configured",
                "summary": "No hay texto suficiente para consultar verificaciones externas.",
                "matches": [],
                "true_hits": 0,
                "false_hits": 0,
            }

        query_variants = [
            query,
            " ".join(query.split()[:10]),
        ]
        query_variants = [item for item in dict.fromkeys(query_variants) if item]

        payload_json: dict = {}
        last_error = ""
        for variant in query_variants:
            endpoints = [
                (
                    "https://factchecktools.googleapis.com/v1alpha1/claims:search"
                    f"?query={quote_plus(variant)}&languageCode=es&key={quote_plus(api_key)}"
                ),
                (
                    "https://factchecktools.googleapis.com/v1alpha1/claims:search"
                    f"?query={quote_plus(variant)}&key={quote_plus(api_key)}"
                ),
            ]
            for endpoint in endpoints:
                logger.info(
                    "Consultando Google Fact Check API para query='%s...'",
                    variant[:80],
                )
                try:
                    request = Request(
                        endpoint,
                        headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"},
                    )
                    with urlopen(request, timeout=self.WEB_TIMEOUT_SECONDS) as response:
                        payload_json = json.loads(response.read().decode("utf-8", errors="ignore"))
                    if payload_json.get("claims"):
                        break
                except Exception as exc:
                    last_error = str(exc)
            if payload_json.get("claims"):
                break

        if not payload_json and last_error:
            logger.warning(
                "Fallo al consultar Google Fact Check API: %s",
                last_error,
            )
            return {
                "status": "configured",
                "summary": "No se pudo consultar Google Fact Check en este momento.",
                "matches": [],
                "true_hits": 0,
                "false_hits": 0,
            }

        claims = payload_json.get("claims", [])[:5]
        matches: list[dict[str, str]] = []
        true_hits = 0
        false_hits = 0
        for claim in claims:
            claim_text = (claim.get("text") or "").strip()
            reviews = claim.get("claimReview", [])
            if not reviews:
                continue
            review = reviews[0]
            publisher = ((review.get("publisher") or {}).get("name") or "Fuente externa").strip()
            rating = (review.get("textualRating") or "Sin calificación").strip()
            url = (review.get("url") or "").strip()
            lower_rating = rating.lower()
            if any(token in lower_rating for token in ["false", "falso", "engañoso", "fake"]):
                false_hits += 1
            if any(token in lower_rating for token in ["true", "verdadero", "correcto"]):
                true_hits += 1
            matches.append(
                {
                    "claim": claim_text[:220] or "Afirmación sin texto",
                    "publisher": publisher,
                    "rating": rating,
                    "url": url,
                }
            )

        logger.info(
            "Google Fact Check API respondio: matches=%s, true_hits=%s, false_hits=%s",
            len(matches),
            true_hits,
            false_hits,
        )
        if matches:
            summary = f"Google Fact Check encontró {len(matches)} coincidencias verificables."
        else:
            summary = "Google Fact Check no devolvió coincidencias para esta consulta."
        return {
            "status": "configured",
            "summary": summary,
            "matches": matches,
            "true_hits": true_hits,
            "false_hits": false_hits,
        }

    def run_external_check(self, query: str) -> dict:
        payload = AnalysisRequest(title=query)
        result = self._query_google_fact_check(payload)
        return {
            "status": result["status"],
            "summary": result["summary"],
            "matches": result["matches"],
        }
