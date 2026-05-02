from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MENTAL_HEALTH_KEYWORDS = [
    "stress",
    "anxiety",
    "depress",
    "mental",
    "mood",
    "wellbeing",
    "burnout",
]

USAGE_KEYWORDS = ["social", "media", "screen", "internet", "phone", "usage", "hours"]
SLEEP_KEYWORDS = ["sleep", "bed", "rest"]
ACTIVITY_KEYWORDS = ["activity", "exercise", "sport", "workout", "physical"]


def resolve_project_path(path_like: Path | str) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else (PROJECT_ROOT / path)


def find_first_csv(raw_dir: Path) -> Path:
    csv_files = sorted(raw_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(
            f"No se encontro ningun CSV en {raw_dir}. Copia el archivo del dataset en esa carpeta."
        )
    return csv_files[0]


def standardize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in df.columns:
        clean = col.strip().lower()
        clean = re.sub(r"[^a-z0-9]+", "_", clean)
        clean = re.sub(r"_+", "_", clean).strip("_")
        rename_map[col] = clean
    return df.rename(columns=rename_map)


def infer_target_column(columns: Iterable[str]) -> Optional[str]:
    cols = list(columns)
    for keyword in MENTAL_HEALTH_KEYWORDS:
        matches = [c for c in cols if keyword in c]
        if matches:
            stress_like = [c for c in matches if "stress" in c]
            return stress_like[0] if stress_like else matches[0]
    return None


def infer_related_columns(columns: Iterable[str]) -> dict[str, list[str]]:
    cols = list(columns)

    def _contains_any(keys: list[str]) -> list[str]:
        return [c for c in cols if any(k in c for k in keys)]

    return {
        "usage": _contains_any(USAGE_KEYWORDS),
        "sleep": _contains_any(SLEEP_KEYWORDS),
        "activity": _contains_any(ACTIVITY_KEYWORDS),
    }


def coerce_target_to_classes(y: pd.Series, n_bins: int = 3) -> pd.Series:
    if pd.api.types.is_numeric_dtype(y):
        nunique = y.nunique(dropna=True)
        if nunique <= 2:
            return y.astype(str)
        q = 3 if nunique >= 3 and n_bins == 3 else 2
        labels = ["bajo", "medio", "alto"] if q == 3 else ["bajo", "alto"]
        return pd.qcut(y.rank(method="first"), q=q, labels=labels, duplicates="drop").astype(str)

    y_clean = y.astype(str).str.strip().str.lower()
    high_patterns = ["high", "alto", "severe", "extreme"]
    low_patterns = ["low", "bajo", "mild", "none"]

    mapped = []
    for val in y_clean:
        if any(p in val for p in high_patterns):
            mapped.append("alto")
        elif any(p in val for p in low_patterns):
            mapped.append("bajo")
        else:
            mapped.append(val)

    mapped_series = pd.Series(mapped, index=y.index)
    if mapped_series.nunique() > 10:
        top_values = mapped_series.value_counts().nlargest(3).index
        mapped_series = mapped_series.where(mapped_series.isin(top_values), "otro")
    return mapped_series
