from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from src.utils import infer_related_columns, infer_target_column, resolve_project_path


def run_eda(
    processed_file: Path | str = "data/processed/cleaned_data.csv",
    images_dir: Path | str = "images",
) -> dict:
    processed_file = resolve_project_path(processed_file)
    images_dir = resolve_project_path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(processed_file)
    sns.set_theme(style="whitegrid")
    plt.rcParams["figure.dpi"] = 140

    target_col = infer_target_column(df.columns)
    if target_col is None:
        raise ValueError("No se detecto columna de estres/salud mental.")

    related = infer_related_columns(df.columns)
    num_cols = df.select_dtypes(include=np.number).columns.tolist()
    cat_cols = df.select_dtypes(exclude=np.number).columns.tolist()

    key_numeric = [c for c in ["daily_social_media_hours", "sleep_hours", "screen_time_before_sleep", "physical_activity", target_col] if c in df.columns]
    for col in key_numeric:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        sns.histplot(df[col], kde=True, ax=ax, color="#4C78A8")
        ax.set_title(f"Distribucion de {col.replace('_', ' ')}")
        ax.set_xlabel(col.replace("_", " "))
        fig.tight_layout()
        fig.savefig(images_dir / f"dist_{col}.png")
        plt.close(fig)

    question_pairs = [
        ("daily_social_media_hours", target_col, "Más uso de redes se asocia con mayor estrés"),
        ("sleep_hours", target_col, "Dormir menos se asocia con mayor estrés"),
        ("screen_time_before_sleep", target_col, "Más pantalla nocturna se asocia con mayor estrés"),
        ("physical_activity", target_col, "Mayor actividad física se asocia con menor estrés"),
    ]
    for x_col, y_col, chart_title in question_pairs:
        if x_col in df.columns and y_col in df.columns:
            fig, ax = plt.subplots(figsize=(8, 4.5))
            sns.regplot(
                data=df,
                x=x_col,
                y=y_col,
                scatter_kws={"alpha": 0.25, "s": 22},
                line_kws={"color": "#F58518"},
                ax=ax,
            )
            ax.set_title(chart_title)
            ax.set_xlabel(x_col.replace("_", " "))
            ax.set_ylabel(y_col.replace("_", " "))
            fig.tight_layout()
            fig.savefig(images_dir / f"rel_{x_col}_vs_{y_col}.png")
            plt.close(fig)

    if "platform_usage" in df.columns and target_col in df.columns:
        platform_stats = (
            df.groupby("platform_usage", as_index=False)[target_col]
            .mean()
            .sort_values(target_col, ascending=False)
        )
        fig, ax = plt.subplots(figsize=(7, 4.5))
        sns.barplot(
            data=platform_stats,
            x="platform_usage",
            y=target_col,
            hue="platform_usage",
            dodge=False,
            legend=False,
            ax=ax,
            palette="viridis",
        )
        ax.set_title("Estrés promedio por tipo de plataforma")
        ax.set_xlabel("platform usage")
        ax.set_ylabel(f"media de {target_col}")
        fig.tight_layout()
        fig.savefig(images_dir / "stress_by_platform.png")
        plt.close(fig)

    if {"social_use_bin", "sleep_bin", target_col}.issubset(df.columns):
        pivot = (
            df.pivot_table(
                index="sleep_bin",
                columns="social_use_bin",
                values=target_col,
                aggfunc="mean",
            )
            .sort_index()
        )
        fig, ax = plt.subplots(figsize=(7, 5))
        sns.heatmap(pivot, annot=True, fmt=".2f", cmap="mako", ax=ax)
        ax.set_title("Interacción sueño vs uso de redes (media de estrés)")
        fig.tight_layout()
        fig.savefig(images_dir / "interaction_sleep_social_vs_stress.png")
        plt.close(fig)

    if len(num_cols) >= 2:
        corr = df[num_cols].corr(numeric_only=True)
        fig, ax = plt.subplots(figsize=(10, 7))
        sns.heatmap(corr, cmap="coolwarm", center=0, annot=True, fmt=".2f", ax=ax)
        ax.set_title("Matriz de correlacion")
        fig.tight_layout()
        fig.savefig(images_dir / "correlation_heatmap.png")
        plt.close(fig)

    insights = {}
    for col in ["daily_social_media_hours", "sleep_hours", "screen_time_before_sleep", "physical_activity"]:
        if col in df.columns and target_col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            insights[f"corr_{col}_vs_{target_col}"] = float(df[[col, target_col]].corr().iloc[0, 1])

    return {
        "shape": df.shape,
        "target_col": target_col,
        "related_columns": related,
        "num_cols": num_cols,
        "cat_cols": cat_cols,
        "insights": insights,
        "processed_file": str(processed_file),
        "images_dir": str(images_dir),
    }


if __name__ == "__main__":
    report = run_eda()
    print("EDA finalizado.")
    for k, v in report.items():
        print(f"{k}: {v}")
