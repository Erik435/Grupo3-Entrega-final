#
import traceback
import uuid
from datetime import datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from processor import enrich_reviews_dataframe
from resolver import SteamGameResolver
from scraper import SteamReviewScraper
from sentiment import SentimentAnalyzer
from utils import to_csv_bytes

APP_NAME = "Steam Scrapping"
APP_TAGLINE = "Extracción, limpieza y análisis de sentimiento sobre reseñas públicas de Steam."

st.set_page_config(page_title=APP_NAME, page_icon="🎮", layout="wide")
st.title(APP_NAME)
st.caption(APP_TAGLINE)
st.subheader("Consulta")


@st.cache_resource
def load_sentiment_model() -> SentimentAnalyzer:
    return SentimentAnalyzer()


def run_pipeline(user_input: str, pages: int) -> tuple[pd.DataFrame, dict]:
    resolver = SteamGameResolver()
    scrape_session = resolver.session
    scraper = SteamReviewScraper(session=scrape_session)

    resolved = resolver.resolve(user_input)
    if resolved.error or not resolved.app_id:
        raise ValueError(resolved.error or "No se pudo resolver el App ID.")

    st.info(f"Juego resuelto: App ID `{resolved.app_id}` (origen: `{resolved.source}`)")

    scrape_progress = st.progress(0, text="Iniciando scraping de reseñas...")

    def on_scrape_progress(current: int, total: int):
        pct = int((current / total) * 100)
        scrape_progress.progress(min(pct, 100), text=f"Scrapeando páginas {current}/{total}...")

    scrape_result = scraper.scrape_reviews(
        app_id=resolved.app_id,
        pages=pages,
        progress_callback=on_scrape_progress,
    )
    scrape_progress.progress(100, text="Scraping completado.")

    if scrape_result.error:
        raise RuntimeError(scrape_result.error)

    if not scrape_result.reviews:
        raise RuntimeError("No se encontraron reseñas públicas para el criterio seleccionado.")

    df = pd.DataFrame(scrape_result.reviews)
    df = enrich_reviews_dataframe(df)

    st.info(
        f"Reseñas obtenidas: `{len(df)}` | Juego detectado: `{scrape_result.game_name or resolved.game_name or resolved.app_id}`"
    )

    analyzer = load_sentiment_model()
    sent_progress = st.progress(0, text="Analizando sentimiento...")
    texts = df["comentario"].fillna("").tolist()

    def on_sent_progress(current: int, total: int):
        pct = int((current / total) * 100)
        sent_progress.progress(min(pct, 100), text=f"Inferencia NLP en lote {current}/{total}...")

    labels, scores = analyzer.predict(texts, batch_size=16, progress_callback=on_sent_progress)
    sent_progress.progress(100, text="Análisis de sentimiento completado.")

    df["sentimiento_modelo"] = labels
    df["score_sentimiento"] = scores
    df["sentimiento_binario"] = df["sentimiento_modelo"].map(
        {"positivo": 1, "neutral": 0, "negativo": -1}
    ).fillna(0)
    df["steam_binario"] = df["recomendacion"].map({"recommended": 1, "not recommended": -1}).fillna(-1)
    df["coincide_steam_sentimiento"] = (
        (df["steam_binario"] == 1) & (df["sentimiento_binario"] >= 0)
    ) | ((df["steam_binario"] == -1) & (df["sentimiento_binario"] <= 0))
    meta = {
        "run_id": str(uuid.uuid4()),
        "timestamp_run": datetime.utcnow().isoformat(timespec="seconds"),
        "app_id": resolved.app_id,
        "juego": scrape_result.game_name or resolved.game_name or f"app_{resolved.app_id}",
        "source_name": "Reseñas públicas (Steam Store)",
        "requested_pages": pages,
    }
    return df, meta


def build_structured_tables(result_df: pd.DataFrame, result_meta: dict) -> dict[str, pd.DataFrame]:
    games_df = (
        result_df[["app_id", "juego"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    reviews_raw_cols = [
        "review_id",
        "app_id",
        "fecha",
        "fecha_scraping",
        "comentario",
        "recomendacion",
        "horas_jugadas",
        "horas_en_review",
        "publicada_recientemente",
        "idioma",
        "votos_util",
        "votos_divertido",
        "fuente_compra",
    ]
    reviews_features_cols = [
        "review_id",
        "longitud_texto",
        "numero_palabras",
        "review_larga",
        "recomendacion_binaria",
        "sentimiento_modelo",
        "score_sentimiento",
        "coincide_steam_sentimiento",
    ]

    reviews_raw_df = result_df[[c for c in reviews_raw_cols if c in result_df.columns]].copy()
    reviews_features_df = result_df[[c for c in reviews_features_cols if c in result_df.columns]].copy()

    scrape_runs_df = pd.DataFrame(
        [
            {
                "run_id": result_meta.get("run_id", ""),
                "timestamp_run": result_meta.get("timestamp_run", ""),
                "app_id": result_meta.get("app_id", ""),
                "juego": result_meta.get("juego", ""),
                "requested_pages": result_meta.get("requested_pages", 0),
                "reviews_obtenidas": len(result_df),
                "source_name": result_meta.get("source_name", "Reseñas públicas (Steam Store)"),
            }
        ]
    )

    return {
        "games.csv": games_df,
        "reviews_raw.csv": reviews_raw_df,
        "reviews_features.csv": reviews_features_df,
        "scrape_runs.csv": scrape_runs_df,
    }


def build_tables_zip_bytes(tables: dict[str, pd.DataFrame]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as zf:
        for filename, table_df in tables.items():
            zf.writestr(filename, table_df.to_csv(index=False))
    return buffer.getvalue()


with st.form("scrape_form"):
    user_input = st.text_input(
        "Juego (nombre, URL de la ficha o App ID)",
        placeholder="Ej: Hollow Knight · URL de store.steampowered.com/app/… · o solo el número del App ID",
    )
    pages = st.slider("Páginas de reseñas a obtener", min_value=1, max_value=20, value=5)
    st.caption("Cada página trae hasta ~100 reseñas. Más páginas = más datos y más tiempo de scraping y NLP.")
    run_btn = st.form_submit_button("Obtener reseñas y analizar sentimiento")

if run_btn:
    if not user_input.strip():
        st.warning("Debes ingresar un nombre, URL o App ID.")
    else:
        try:
            df, meta = run_pipeline(user_input=user_input, pages=pages)
            st.session_state["last_df"] = df
            st.session_state["last_meta"] = meta
        except Exception as exc:
            st.error(f"Ocurrió un error: {exc}")
            with st.expander("Ver detalle técnico"):
                st.code(traceback.format_exc())


if "last_df" in st.session_state:
    result_df: pd.DataFrame = st.session_state["last_df"]
    result_meta: dict = st.session_state.get("last_meta", {})

    st.divider()
    st.subheader("Trazabilidad del scraping")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("App ID scrapeado", int(result_meta.get("app_id", 0)))
    m2.metric("Páginas solicitadas", int(result_meta.get("requested_pages", 0)))
    m3.metric("Reviews scrapeadas", int(len(result_df)))
    m4.metric("Fecha de scraping", str(result_df["fecha_scraping"].max()) if "fecha_scraping" in result_df.columns else "-")
    st.caption(f"Fuente principal de datos scrapeados: `{result_meta.get('source_name', 'Steam Public Reviews')}`")

    st.subheader("Muestra de datos crudos")
    raw_cols = [
        "app_id",
        "juego",
        "review_id",
        "fecha",
        "fecha_scraping",
        "recomendacion",
        "idioma",
        "horas_jugadas",
        "horas_en_review",
        "votos_util",
        "votos_divertido",
        "fuente_compra",
        "comentario",
    ]
    raw_cols = [col for col in raw_cols if col in result_df.columns]
    st.dataframe(result_df[raw_cols].head(5), width="stretch", height=220)

    st.subheader("Calidad del dataset")
    total_reviews = len(result_df)
    empty_comments = int((result_df["comentario"].fillna("").str.strip() == "").sum())
    duplicate_review_ids = int(result_df["review_id"].fillna("").duplicated().sum()) if "review_id" in result_df.columns else 0
    null_dates = int(result_df["fecha"].fillna("").eq("").sum())
    avg_words = float(result_df["numero_palabras"].fillna(0).mean()) if total_reviews else 0.0
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Comentarios vacíos", empty_comments)
    q2.metric("Review IDs duplicados", duplicate_review_ids)
    q3.metric("Fechas faltantes", null_dates)
    q4.metric("Prom. palabras/review", f"{avg_words:.1f}")

    st.subheader("Tabla completa")
    st.dataframe(result_df, width="stretch", height=420)

    st.subheader("Gráficos")
    if "fecha" in result_df.columns:
        temporal_df = result_df.copy()
        temporal_df["fecha_dt"] = pd.to_datetime(temporal_df["fecha"], errors="coerce")
        temporal_df = temporal_df.dropna(subset=["fecha_dt"])
        if not temporal_df.empty:
            trend_reviews = (
                temporal_df.groupby("fecha_dt", as_index=False)
                .size()
                .rename(columns={"size": "reviews_por_dia"})
                .sort_values("fecha_dt")
            )
            st.write("Evolución de volumen de reviews por fecha")
            st.line_chart(trend_reviews.set_index("fecha_dt"))

            trend_score = (
                temporal_df.groupby("fecha_dt", as_index=False)["score_sentimiento"]
                .mean()
                .rename(columns={"score_sentimiento": "score_promedio"})
                .sort_values("fecha_dt")
            )
            st.write("Evolución del score promedio de sentimiento")
            st.line_chart(trend_score.set_index("fecha_dt"))

    extra1, extra2 = st.columns(2)
    with extra1:
        if "idioma" in result_df.columns:
            st.write("Top idiomas en reviews scrapeadas")
            lang_counts = (
                result_df["idioma"]
                .fillna("")
                .replace("", "unknown")
                .value_counts()
                .head(10)
                .rename_axis("idioma")
                .reset_index(name="conteo")
            )
            st.bar_chart(lang_counts.set_index("idioma"))
    with extra2:
        if "fuente_compra" in result_df.columns:
            st.write("Fuente de compra reportada")
            src_counts = (
                result_df["fuente_compra"]
                .fillna("")
                .replace("", "unknown")
                .value_counts()
                .head(10)
                .rename_axis("fuente_compra")
                .reset_index(name="conteo")
            )
            st.bar_chart(src_counts.set_index("fuente_compra"))

    total_positive = int((result_df["sentimiento_modelo"] == "positivo").sum())
    total_negative = int((result_df["sentimiento_modelo"] == "negativo").sum())
    total_neutral = int((result_df["sentimiento_modelo"] == "neutral").sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total reviews", total_reviews)
    c2.metric("Positivas", total_positive)
    c3.metric("Negativas", total_negative)
    c4.metric("Neutrales", total_neutral)

    st.subheader("Sentimiento (modelo)")
    sentiment_counts = result_df["sentimiento_modelo"].value_counts().rename_axis("sentimiento").reset_index(name="conteo")
    st.bar_chart(sentiment_counts.set_index("sentimiento"))

    st.subheader("Recomendación (Steam)")
    recommendation_counts = (
        result_df["recomendacion"].value_counts().rename_axis("recomendacion").reset_index(name="conteo")
    )
    st.bar_chart(recommendation_counts.set_index("recomendacion"))

    st.subheader("Síntesis · recomendación orientativa")
    avg_sentiment_score = (
        (result_df["sentimiento_binario"] * result_df["score_sentimiento"]).mean() + 1
    ) / 2
    avg_steam_score = ((result_df["steam_binario"]).mean() + 1) / 2
    final_score = (0.65 * avg_steam_score) + (0.35 * avg_sentiment_score)
    mismatch_rate = 1 - float(result_df["coincide_steam_sentimiento"].mean())

    if final_score >= 0.62 and mismatch_rate <= 0.35:
        verdict = "SI, se recomienda"
        verdict_color = "green"
    elif final_score <= 0.45:
        verdict = "NO, no se recomienda"
        verdict_color = "red"
    else:
        verdict = "Mixto / depende del perfil de jugador"
        verdict_color = "orange"

    st.markdown(
        f"**Recomendación final:** :{verdict_color}[{verdict}]  \n"
        f"**Score final (0-100):** `{final_score * 100:.1f}`  \n"
        f"**Contradicción Steam vs sentimiento:** `{mismatch_rate * 100:.1f}%`"
    )
    st.caption(
        "El score final combina recomendación de Steam (65%) + tono del texto detectado por el modelo (35%)."
    )

    st.subheader("Resumen en texto")
    ratio_pos = (total_positive / total_reviews) * 100 if total_reviews else 0
    ratio_recommended = (
        (result_df["recomendacion"] == "recommended").mean() * 100 if total_reviews else 0
    )
    st.write(
        f"- El modelo clasifica **{ratio_pos:.1f}%** de comentarios como positivos.\n"
        f"- En Steam, **{ratio_recommended:.1f}%** de las reseñas obtenidas recomiendan el juego.\n"
        f"- Se analizaron **{total_reviews}** reviews con texto limpio y variables derivadas.\n"
        f"- El veredicto final del juego fue: **{verdict}**."
    )

    with st.expander("Ver reviews con contradicción (útiles para analizar contexto)"):
        mismatch_df = result_df.loc[~result_df["coincide_steam_sentimiento"]].copy()
        st.write(f"Total de contradicciones detectadas: **{len(mismatch_df)}**")
        if not mismatch_df.empty:
            st.dataframe(
                mismatch_df[
                    [
                        "fecha",
                        "recomendacion",
                        "sentimiento_modelo",
                        "score_sentimiento",
                        "horas_jugadas",
                        "comentario",
                    ]
                ],
                width="stretch",
                height=260,
            )

    csv_bytes = to_csv_bytes(
        result_df[
            [
                "app_id",
                "juego",
                "review_id",
                "fecha",
                "fecha_scraping",
                "comentario",
                "recomendacion",
                "horas_jugadas",
                "horas_en_review",
                "publicada_recientemente",
                "idioma",
                "votos_util",
                "votos_divertido",
                "fuente_compra",
                "longitud_texto",
                "numero_palabras",
                "review_larga",
                "recomendacion_binaria",
                "sentimiento_modelo",
                "score_sentimiento",
                "coincide_steam_sentimiento",
            ]
        ]
    )
    st.download_button(
        "Descargar CSV",
        data=csv_bytes,
        file_name="steam_reviews_sentiment.csv",
        mime="text/csv",
    )

    st.subheader("Exportación (CSV y tablas)")
    st.caption("Separa datos scrapeados en tablas lógicas para facilitar análisis y trazabilidad.")
    structured_tables = build_structured_tables(result_df, result_meta)
    cexp1, cexp2 = st.columns(2)
    with cexp1:
        st.download_button(
            "Descargar ZIP con tablas estructuradas",
            data=build_tables_zip_bytes(structured_tables),
            file_name="steam_reviews_structured_tables.zip",
            mime="application/zip",
        )
    with cexp2:
        st.write("Tablas incluidas: `games`, `reviews_raw`, `reviews_features`, `scrape_runs`.")

    with st.expander("Descarga individual por tabla"):
        for table_name, table_df in structured_tables.items():
            st.download_button(
                f"Descargar {table_name}",
                data=to_csv_bytes(table_df),
                file_name=table_name,
                mime="text/csv",
                key=f"dl_{table_name}",
            )
