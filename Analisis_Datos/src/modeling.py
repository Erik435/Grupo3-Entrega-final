from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
import seaborn as sns
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.utils import coerce_target_to_classes, infer_target_column, resolve_project_path


MENTAL_HEALTH_LEAKAGE_KEYWORDS = [
    "stress",
    "anxiety",
    "depress",
    "addiction",
    "mental",
    "mood",
    "psych",
    "burnout",
]


def detect_mental_health_columns(columns: list[str]) -> list[str]:
    return [
        col
        for col in columns
        if any(keyword in col.lower() for keyword in MENTAL_HEALTH_LEAKAGE_KEYWORDS)
    ]


def build_preprocessor(X_train: pd.DataFrame) -> ColumnTransformer:
    num_cols = X_train.select_dtypes(include=np.number).columns.tolist()
    cat_cols = X_train.select_dtypes(exclude=np.number).columns.tolist()

    return ColumnTransformer(
        transformers=[
            (
                "num",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                num_cols,
            ),
            (
                "cat",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("encoder", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                cat_cols,
            ),
        ]
    )


def train_and_evaluate_models(X: pd.DataFrame, y: pd.Series, random_state: int = 42) -> dict:
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=random_state, stratify=y
    )

    preprocessor = build_preprocessor(X_train)

    models: dict[str, object] = {
        "Logistic Regression": LogisticRegression(max_iter=2000),
        "Random Forest": RandomForestClassifier(
            n_estimators=400, random_state=random_state, class_weight="balanced"
        ),
    }

    results = {}
    for name, clf in models.items():
        pipe = Pipeline(steps=[("prep", preprocessor), ("model", clf)])
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=random_state)
        cv_scores = cross_validate(
            pipe,
            X,
            y,
            cv=cv,
            scoring=["accuracy", "f1_weighted", "precision_weighted", "recall_weighted"],
            n_jobs=None,
        )
        pipe.fit(X_train, y_train)
        pred = pipe.predict(X_test)

        precision, recall, f1, _ = precision_recall_fscore_support(
            y_test, pred, average="weighted", zero_division=0
        )
        results[name] = {
            "pipeline": pipe,
            "accuracy": float(accuracy_score(y_test, pred)),
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "confusion_matrix": confusion_matrix(y_test, pred),
            "classification_report": classification_report(y_test, pred, zero_division=0),
            "cv_accuracy_mean": float(np.mean(cv_scores["test_accuracy"])),
            "cv_f1_weighted_mean": float(np.mean(cv_scores["test_f1_weighted"])),
            "cv_precision_weighted_mean": float(np.mean(cv_scores["test_precision_weighted"])),
            "cv_recall_weighted_mean": float(np.mean(cv_scores["test_recall_weighted"])),
        }

    scores = pd.DataFrame(
        {
            name: {
                "accuracy": val["accuracy"],
                "precision": val["precision"],
                "recall": val["recall"],
                "f1": val["f1"],
                "cv_accuracy_mean": val["cv_accuracy_mean"],
                "cv_f1_weighted_mean": val["cv_f1_weighted_mean"],
                "cv_precision_weighted_mean": val["cv_precision_weighted_mean"],
                "cv_recall_weighted_mean": val["cv_recall_weighted_mean"],
            }
            for name, val in results.items()
        }
    ).T.sort_values("f1", ascending=False)

    return {"results": results, "scores": scores, "y_test": y_test}


def plot_confusion_matrices(results: dict, title_prefix: str = "") -> None:
    for model_name, metrics in results.items():
        plt.figure(figsize=(5, 4))
        sns.heatmap(metrics["confusion_matrix"], annot=True, fmt="d", cmap="Blues")
        plt.title(f"{title_prefix}{model_name}")
        plt.xlabel("Prediccion")
        plt.ylabel("Real")
        plt.tight_layout()
        plt.show()


def run_modeling(processed_file: Path | str = "data/processed/model_ready.csv") -> dict:
    processed_file = resolve_project_path(processed_file)
    df = pd.read_csv(processed_file)

    target_col = infer_target_column(df.columns)
    if target_col is None:
        raise ValueError("No se detecto una columna target relacionada con estres/salud mental.")

    y = coerce_target_to_classes(df[target_col])
    X_full = df.drop(columns=[target_col]).copy()

    valid_idx = y.notna()
    X_full = X_full.loc[valid_idx].copy()
    y = y.loc[valid_idx].copy()

    leakage_candidates = [
        c for c in detect_mental_health_columns(X_full.columns.tolist()) if c != "depression_label"
    ]
    X_no_leak = X_full.drop(columns=leakage_candidates, errors="ignore")

    original_out = train_and_evaluate_models(X_full, y)
    no_leak_out = train_and_evaluate_models(X_no_leak, y)

    rf_pipe_original = original_out["results"]["Random Forest"]["pipeline"]
    rf_model_original = rf_pipe_original.named_steps["model"]
    rf_features_original = rf_pipe_original.named_steps["prep"].get_feature_names_out()
    fi_original = (
        pd.DataFrame(
            {"feature": rf_features_original, "importance": rf_model_original.feature_importances_}
        )
        .sort_values("importance", ascending=False)
        .head(20)
    )

    rf_pipe_no_leak = no_leak_out["results"]["Random Forest"]["pipeline"]
    rf_model_no_leak = rf_pipe_no_leak.named_steps["model"]
    rf_features_no_leak = rf_pipe_no_leak.named_steps["prep"].get_feature_names_out()
    fi_no_leak = (
        pd.DataFrame(
            {"feature": rf_features_no_leak, "importance": rf_model_no_leak.feature_importances_}
        )
        .sort_values("importance", ascending=False)
        .head(20)
    )

    return {
        "target_col": target_col,
        "processed_file": str(processed_file),
        "target_distribution": y.value_counts().to_dict(),
        "leakage_columns_removed": leakage_candidates,
        "scores_original": original_out["scores"],
        "scores_no_leakage": no_leak_out["scores"],
        "scores_comparison": pd.concat(
            [
                original_out["scores"].assign(scenario="original_con_fuga"),
                no_leak_out["scores"].assign(scenario="sin_fuga"),
            ]
        )
        .set_index("scenario", append=True)
        .reorder_levels(["scenario", None])
        .sort_index(),
        "results_original": original_out["results"],
        "results_no_leakage": no_leak_out["results"],
        "feature_importance_top20_original": fi_original,
        "feature_importance_top20_no_leakage": fi_no_leak,
    }


if __name__ == "__main__":
    out = run_modeling()
    print("Modelado finalizado.")
    print("Target detectado:", out["target_col"])
    print(out["scores_comparison"])