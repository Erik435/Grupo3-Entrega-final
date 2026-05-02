import pandas as pd


def enrich_reviews_dataframe(df: pd.DataFrame, long_review_threshold: int = 120) -> pd.DataFrame:
    #Estructura en columnas
    """Añade columnas derivadas para análisis."""
    if df.empty:
        return df

    out = df.copy()
    out["comentario"] = out["comentario"].fillna("")
    out["longitud_texto"] = out["comentario"].str.len()
    out["numero_palabras"] = out["comentario"].str.split().str.len()
    out["review_larga"] = out["numero_palabras"] >= long_review_threshold
    out["recomendacion_binaria"] = out["recomendacion"].map(
        {"recommended": 1, "not recommended": 0}
    ).fillna(0).astype(int)
    return out
