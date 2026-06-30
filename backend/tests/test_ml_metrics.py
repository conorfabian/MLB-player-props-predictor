from __future__ import annotations

import pandas as pd

from ml.metrics import (
    binary_classification_metrics,
    calibration_table,
    daily_top_k_metrics,
)


def test_metrics_handle_single_class_without_roc_auc() -> None:
    metrics = binary_classification_metrics(
        [True, True, True],
        [0.6, 0.7, 0.8],
    )

    assert metrics["examples"] == 3
    assert metrics["roc_auc"] is None
    assert metrics["positive_rate"] == 1.0


def test_top_k_daily_metric_uses_known_fake_slates() -> None:
    df = pd.DataFrame(
        {
            "game_date": [
                "2026-06-01",
                "2026-06-01",
                "2026-06-01",
                "2026-06-02",
                "2026-06-02",
                "2026-06-02",
            ],
            "target_over": [True, False, True, False, True, False],
        }
    )
    metrics = daily_top_k_metrics(df, [0.9, 0.8, 0.1, 0.7, 0.6, 0.5])

    assert metrics["number_of_slates"] == 2
    assert metrics["total_candidates"] == 6
    assert metrics["average_candidates_per_slate"] == 3
    assert metrics["median_candidates_per_slate"] == 3
    assert metrics["min_candidates_per_slate"] == 3
    assert metrics["max_candidates_per_slate"] == 3
    assert metrics["average_slate_actual_rate"] == 0.5
    assert metrics["top_1_hit_rate"] == 0.5
    assert metrics["top_1_average_slate_hit_rate"] == 0.5
    assert metrics["top_3_slates_with_at_least_k"] == 2
    assert metrics["top_3_hit_rate"] == 0.5


def test_calibration_buckets_count_expected_rows() -> None:
    table = calibration_table(
        [False, True, True, False, True, False],
        [0.49, 0.50, 0.54, 0.60, 0.69, 0.95],
    )

    counts = {row["bucket"]: row["count"] for row in table}
    assert counts == {
        "0.00-0.50": 2,
        "0.50-0.55": 1,
        "0.55-0.60": 1,
        "0.60-0.65": 0,
        "0.65-0.70": 1,
        "0.70-1.00": 1,
    }
    assert table[0]["actual_hit_rate"] == 0.5
