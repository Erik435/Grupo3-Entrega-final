from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.utils import find_first_csv, resolve_project_path, standardize_column_names


def run_data_cleaning(
    raw_dir: Path | str = "data/raw",
    processed_dir: Path | str = "data/processed",
    output_name: str = "cleaned_data.csv",
    model_ready_name: str = "model_ready.csv",
) -> tuple[pd.DataFrame, dict]:
    raw_dir = resolve_project_path(raw_dir)
    processed_dir = resolve_project_path(processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)

    csv_path = find_first_csv(raw_dir)
    df_raw = pd.read_csv(csv_path)

    report: dict = {
        "input_file": str(csv_path),
        "shape_original": df_raw.shape,
        "nulls_before": df_raw.isna().sum().to_dict(),
    }

    df = standardize_column_names(df_raw)
    df.columns = [c.lower() for c in df.columns]

    before = len(df)
    df = df.drop_duplicates().copy()
    report["duplicates_removed"] = before - len(df)

    num_cols = df.select_dtypes(include=np.number).columns.tolist()
    cat_cols = df.select_dtypes(exclude=np.number).columns.tolist()

    for col in num_cols:
        df[col] = df[col].fillna(df[col].median())

    for col in cat_cols:
        mode_val = df[col].mode(dropna=True)
        df[col] = df[col].fillna(mode_val.iloc[0] if not mode_val.empty else "desconocido")

    if "gender" in df.columns:
        df["gender"] = df["gender"].astype(str).str.strip().str.lower()

    if "platform_usage" in df.columns:
        df["platform_usage"] = df["platform_usage"].astype(str).str.strip().str.lower()

    if "social_interaction_level" in df.columns:
        df["social_interaction_level"] = (
            df["social_interaction_level"].astype(str).str.strip().str.lower()
        )

    # Keep teenage range and plausible usage ranges for better analytical quality.
    range_rules = {
        "age": (12, 19),
        "daily_social_media_hours": (0, 16),
        "sleep_hours": (0, 14),
        "screen_time_before_sleep": (0, 8),
        "physical_activity": (0, 8),
    }
    for col, (low, high) in range_rules.items():
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].clip(lower=low, upper=high)

    report["nulls_after"] = int(df.isna().sum().sum())

    outlier_report = {}
    winsorized_bounds: dict[str, dict[str, float]] = {}
    for col in num_cols:
        q1 = df[col].quantile(0.25)
        q3 = df[col].quantile(0.75)
        iqr = q3 - q1
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        outlier_report[col] = int(((df[col] < low) | (df[col] > high)).sum())
        p01 = float(df[col].quantile(0.01))
        p99 = float(df[col].quantile(0.99))
        df[col] = df[col].clip(lower=p01, upper=p99)
        winsorized_bounds[col] = {"p01": p01, "p99": p99}
    report["outliers_iqr_count"] = outlier_report
    report["winsorization_bounds"] = winsorized_bounds

    if "daily_social_media_hours" in df.columns:
        usage_labels = ["bajo", "medio", "alto"]
        df["social_use_bin"] = pd.qcut(
            df["daily_social_media_hours"].rank(method="first"),
            q=3,
            labels=usage_labels,
            duplicates="drop",
        ).astype(str)
        df["high_social_use"] = (df["daily_social_media_hours"] >= df["daily_social_media_hours"].quantile(0.75)).astype(int)

    if "sleep_hours" in df.columns:
        df["sleep_bin"] = pd.cut(
            df["sleep_hours"],
            bins=[-np.inf, 5.99, 8.0, np.inf],
            labels=["insuficiente", "normal", "alta"],
        ).astype(str)
        df["sleep_deficit"] = (df["sleep_hours"] < 6).astype(int)

    if "screen_time_before_sleep" in df.columns:
        df["night_screen_risk"] = (df["screen_time_before_sleep"] > 2).astype(int)

    if {"daily_social_media_hours", "screen_time_before_sleep", "sleep_hours"}.issubset(df.columns):
        z_use = (df["daily_social_media_hours"] - df["daily_social_media_hours"].mean()) / (df["daily_social_media_hours"].std() + 1e-9)
        z_screen = (df["screen_time_before_sleep"] - df["screen_time_before_sleep"].mean()) / (df["screen_time_before_sleep"].std() + 1e-9)
        z_sleep = (df["sleep_hours"].mean() - df["sleep_hours"]) / (df["sleep_hours"].std() + 1e-9)
        df["wellbeing_risk_score"] = (0.45 * z_use + 0.35 * z_screen + 0.20 * z_sleep).round(3)

    output_path = processed_dir / output_name
    df.to_csv(output_path, index=False)

    model_df = df.copy()
    leakage_cols = [c for c in ["anxiety_level", "addiction_level"] if c in model_df.columns]
    model_df = model_df.drop(columns=leakage_cols, errors="ignore")
    model_ready_path = processed_dir / model_ready_name
    model_df.to_csv(model_ready_path, index=False)

    report["output_file"] = str(output_path)
    report["model_ready_file"] = str(model_ready_path)
    report["leakage_columns_removed_for_model"] = leakage_cols
    report["shape_final"] = df.shape
    return df, report


if __name__ == "__main__":
    _, cleaning_report = run_data_cleaning()
    print("Limpieza finalizada.")
    for k, v in cleaning_report.items():
        print(f"{k}: {v}")
