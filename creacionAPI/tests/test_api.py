from fastapi.testclient import TestClient

from app.main import app
from app.services.web_scraper import FetchResult

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analyze_site_ok(monkeypatch) -> None:
    html = """
    <html>
        <head>
            <title>Mi Sitio de Prueba</title>
            <meta name="description" content="Descripcion de prueba para validar la API" />
        </head>
        <body>
            <h1>Titulo Principal</h1>
            <h2>Seccion A</h2>
            <a href="/interno">Interno</a>
            <a href="https://externo.com">Externo</a>
            <img src="a.jpg" alt="img a" />
            <img src="b.jpg" />
            <p>{}</p>
        </body>
    </html>
    """.format(
        "palabra " * 320
    )

    def fake_fetch(_self, _url: str) -> FetchResult:
        return FetchResult(
            url="https://example.com",
            status_code=200,
            response_time_ms=120.1,
            html=html,
        )

    monkeypatch.setattr("app.services.analyzer.WebScraper.fetch", fake_fetch)

    response = client.post("/analyze-site", json={"url": "https://example.com"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["url"] == "https://example.com"
    assert payload["status_code"] == 200
    assert payload["h1_count"] == 1
    assert payload["internal_links"] == 1
    assert payload["external_links"] == 1
    assert payload["scores"]["overall_score"] >= 0


def test_compare_sites(monkeypatch) -> None:
    html = "<html><head><title>X</title></head><body><h1>X</h1><p>{}</p></body></html>".format(
        "dato " * 350
    )

    def fake_fetch(_self, url: str) -> FetchResult:
        return FetchResult(
            url=url,
            status_code=200,
            response_time_ms=80,
            html=html,
        )

    monkeypatch.setattr("app.services.analyzer.WebScraper.fetch", fake_fetch)

    response = client.post(
        "/compare-sites",
        json={"urls": ["https://site-a.com", "https://site-b.com"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 2
    assert len(data["ranking"]) == 2
    assert data["comparative_observations"]