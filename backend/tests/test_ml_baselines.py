from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.baselines import (
    GlobalPositiveRateBaseline,
    LogisticRegressionBaseline,
    RuleBasedHitRateBaseline,
)
from ml.data import FEATURE_COLUMNS, validate_feature_columns


def test_leakage_columns_are_excluded_from_feature_columns() -> None:
    assert "actual_hits" not in FEATURE_COLUMNS
    assert "target_over" not in FEATURE_COLUMNS
    assert "id" not in FEATURE_COLUMNS
    with pytest.raises(ValueError, match="leakage"):
        validate_feature_columns((*FEATURE_COLUMNS, "actual_hits"))


def test_rule_baseline_fallback_order() -> None:
    train_df = pd.DataFrame(
        {
            "target_over": [True, False, True, False],
            "hit_rate_last_10": [0.1, 0.2, 0.3, 0.4],
            "season_hit_rate_before": [0.5, 0.5, 0.5, 0.5],
        }
    )
    predict_df = pd.DataFrame(
        {
            "hit_rate_last_10": [0.7, np.nan, np.nan],
            "season_hit_rate_before": [0.2, 0.6, np.nan],
        }
    )

    model = RuleBasedHitRateBaseline().fit(train_df)

    assert model.predict_proba(predict_df).tolist() == [0.7, 0.6, 0.5]


def test_rule_baseline_clips_extreme_probabilities() -> None:
    train_df = pd.DataFrame(
        {
            "target_over": [True, False],
            "hit_rate_last_10": [1.0, 0.0],
            "season_hit_rate_before": [1.0, 0.0],
        }
    )
    predict_df = pd.DataFrame(
        {
            "hit_rate_last_10": [1.0, 0.0],
            "season_hit_rate_before": [np.nan, np.nan],
        }
    )

    model = RuleBasedHitRateBaseline().fit(train_df)

    assert model.predict_proba(predict_df).tolist() == [0.99, 0.01]


def test_global_positive_rate_baseline_predicts_train_rate() -> None:
    train_df = pd.DataFrame({"target_over": [True, True, False, False]})

    model = GlobalPositiveRateBaseline().fit(train_df)

    assert model.predict_proba(pd.DataFrame(index=range(3))).tolist() == [
        0.5,
        0.5,
        0.5,
    ]


def test_logistic_regression_uses_train_medians_only() -> None:
    train_df = _feature_frame(
        target=[False, True, False, True],
        line=[0.5, 1.5, np.nan, 2.5],
    )
    test_df = _feature_frame(
        target=[False, True],
        line=[100.0, np.nan],
    )

    model = LogisticRegressionBaseline().fit(train_df)
    probabilities = model.predict_proba(test_df)

    assert model.medians_ is not None
    assert model.medians_["line"] == pytest.approx(1.5)
    assert len(probabilities) == 2
    assert all(0.0 <= probability <= 1.0 for probability in probabilities)


def _feature_frame(
    *,
    target: list[bool],
    line: list[float],
) -> pd.DataFrame:
    data: dict[str, object] = {"target_over": target}
    for column in FEATURE_COLUMNS:
        data[column] = [1.0] * len(target)
    data["line"] = line
    data["hit_rate_last_10"] = [0.2, 0.8, 0.3, 0.7][: len(target)]
    data["season_hit_rate_before"] = [0.4] * len(target)
    return pd.DataFrame(data)
