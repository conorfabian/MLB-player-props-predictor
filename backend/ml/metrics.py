from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

from ml.data import TARGET_COLUMN

CALIBRATION_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("0.00-0.50", 0.00, 0.50),
    ("0.50-0.55", 0.50, 0.55),
    ("0.55-0.60", 0.55, 0.60),
    ("0.60-0.65", 0.60, 0.65),
    ("0.65-0.70", 0.65, 0.70),
    ("0.70-1.00", 0.70, 1.00),
)


def binary_classification_metrics(
    y_true: Sequence[bool] | Sequence[int] | pd.Series,
    y_prob: Sequence[float] | np.ndarray,
) -> dict[str, float | int | None]:
    true = np.asarray(y_true, dtype=int)
    prob = np.clip(np.asarray(y_prob, dtype=float), 1e-15, 1 - 1e-15)
    pred = prob >= 0.5
    if len(true) == 0:
        raise ValueError("Cannot compute metrics for an empty split.")

    metrics: dict[str, float | int | None] = {
        "examples": int(len(true)),
        "positive_rate": float(np.mean(true)),
        "accuracy_at_0_5": float(accuracy_score(true, pred)),
        "precision_at_0_5": float(
            precision_score(true, pred, zero_division=0)
        ),
        "recall_at_0_5": float(recall_score(true, pred, zero_division=0)),
        "log_loss": float(log_loss(true, prob, labels=[0, 1])),
        "brier_score": float(brier_score_loss(true, prob)),
        "roc_auc": None,
        "average_predicted_probability": float(np.mean(prob)),
        "average_actual_rate": float(np.mean(true)),
    }
    if len(np.unique(true)) == 2:
        metrics["roc_auc"] = float(roc_auc_score(true, prob))
    return metrics


def daily_top_k_metrics(
    df: pd.DataFrame,
    y_prob: Sequence[float] | np.ndarray,
    k_values: Iterable[int] = (1, 3, 5, 10),
    ) -> dict[str, float | int | None]:
    k_values = tuple(k_values)
    if df.empty:
        return {
            "number_of_slates": 0,
            "total_candidates": 0,
            "average_candidates_per_slate": None,
            "median_candidates_per_slate": None,
            "min_candidates_per_slate": None,
            "max_candidates_per_slate": None,
            "average_slate_actual_rate": None,
            **{f"top_{k}_hit_rate": None for k in k_values},
            **{f"top_{k}_average_slate_hit_rate": None for k in k_values},
            **{f"top_{k}_slates_with_at_least_k": 0 for k in k_values},
        }

    eval_df = df.loc[:, ["game_date", TARGET_COLUMN]].copy()
    eval_df["predicted_probability"] = np.asarray(y_prob, dtype=float)
    slate_sizes = eval_df.groupby("game_date").size()
    slate_actual_rates = eval_df.groupby("game_date")[TARGET_COLUMN].mean()
    result: dict[str, float | int | None] = {
        "number_of_slates": int(slate_sizes.size),
        "total_candidates": int(len(eval_df)),
        "average_candidates_per_slate": float(slate_sizes.mean()),
        "median_candidates_per_slate": float(slate_sizes.median()),
        "min_candidates_per_slate": int(slate_sizes.min()),
        "max_candidates_per_slate": int(slate_sizes.max()),
        "average_slate_actual_rate": float(slate_actual_rates.mean()),
    }

    for k in k_values:
        selected = (
            eval_df.sort_values(
                ["game_date", "predicted_probability"],
                ascending=[True, False],
            )
            .groupby("game_date", group_keys=False)
            .head(k)
        )
        slate_top_rates = selected.groupby("game_date")[TARGET_COLUMN].mean()
        result[f"top_{k}_hit_rate"] = (
            float(selected[TARGET_COLUMN].astype(int).mean())
            if not selected.empty
            else None
        )
        result[f"top_{k}_average_slate_hit_rate"] = (
            float(slate_top_rates.mean()) if not slate_top_rates.empty else None
        )
        result[f"top_{k}_min_slate_hit_rate"] = (
            float(slate_top_rates.min()) if not slate_top_rates.empty else None
        )
        result[f"top_{k}_max_slate_hit_rate"] = (
            float(slate_top_rates.max()) if not slate_top_rates.empty else None
        )
        result[f"top_{k}_average_picks_per_slate"] = (
            float(selected.groupby("game_date").size().mean())
            if not selected.empty
            else None
        )
        result[f"top_{k}_slates_with_at_least_k"] = int((slate_sizes >= k).sum())
    return result


def calibration_table(
    y_true: Sequence[bool] | Sequence[int] | pd.Series,
    y_prob: Sequence[float] | np.ndarray,
) -> list[dict[str, float | int | str | None]]:
    true = np.asarray(y_true, dtype=int)
    prob = np.asarray(y_prob, dtype=float)
    rows: list[dict[str, float | int | str | None]] = []

    for index, (label, lower, upper) in enumerate(CALIBRATION_BUCKETS):
        if index == 0:
            mask = (prob >= lower) & (prob <= upper)
        elif index == len(CALIBRATION_BUCKETS) - 1:
            mask = (prob >= lower) & (prob <= upper)
        else:
            mask = (prob > lower) & (prob <= upper)
        bucket_true = true[mask]
        bucket_prob = prob[mask]
        rows.append(
            {
                "bucket": label,
                "count": int(mask.sum()),
                "average_predicted_probability": (
                    float(bucket_prob.mean()) if len(bucket_prob) else None
                ),
                "actual_hit_rate": (
                    float(bucket_true.mean()) if len(bucket_true) else None
                ),
            }
        )
    return rows
