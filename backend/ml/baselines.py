from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from ml.data import FEATURE_COLUMNS, TARGET_COLUMN, validate_feature_columns

MIN_PREDICTED_PROBABILITY = 0.01
MAX_PREDICTED_PROBABILITY = 0.99


def clip_probabilities(probabilities: pd.Series | np.ndarray) -> np.ndarray:
    return np.clip(
        np.asarray(probabilities, dtype=float),
        MIN_PREDICTED_PROBABILITY,
        MAX_PREDICTED_PROBABILITY,
    )


class GlobalPositiveRateBaseline:
    name = "global_positive_rate"

    def __init__(self) -> None:
        self.global_positive_rate_: float | None = None

    def fit(self, train_df: pd.DataFrame) -> "GlobalPositiveRateBaseline":
        if train_df.empty:
            raise ValueError("Cannot fit global baseline with no training rows.")
        self.global_positive_rate_ = float(train_df[TARGET_COLUMN].mean())
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        if self.global_positive_rate_ is None:
            raise ValueError("GlobalPositiveRateBaseline must be fit first.")
        return clip_probabilities(
            np.full(len(df), self.global_positive_rate_, dtype=float)
        )


class RuleBasedHitRateBaseline:
    name = "rule_based_hit_rate"

    def __init__(self) -> None:
        self.global_positive_rate_: float | None = None

    def fit(self, train_df: pd.DataFrame) -> "RuleBasedHitRateBaseline":
        if train_df.empty:
            raise ValueError("Cannot fit rule baseline with no training rows.")
        self.global_positive_rate_ = float(train_df[TARGET_COLUMN].mean())
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        if self.global_positive_rate_ is None:
            raise ValueError("RuleBasedHitRateBaseline must be fit first.")
        probabilities = (
            df["hit_rate_last_10"]
            .combine_first(df["season_hit_rate_before"])
            .fillna(self.global_positive_rate_)
            .astype(float)
        )
        return clip_probabilities(probabilities)


class LogisticRegressionBaseline:
    name = "logistic_regression"

    def __init__(
        self,
        *,
        feature_columns: tuple[str, ...] = FEATURE_COLUMNS,
    ) -> None:
        self.feature_columns = validate_feature_columns(feature_columns)
        self.model_: LogisticRegression | None = None
        self.medians_: pd.Series | None = None
        self.means_: pd.Series | None = None
        self.stds_: pd.Series | None = None

    def fit(self, train_df: pd.DataFrame) -> "LogisticRegressionBaseline":
        if train_df.empty:
            raise ValueError(
                "Cannot fit logistic regression with no training rows."
            )
        y = train_df[TARGET_COLUMN].astype(int)
        if y.nunique() < 2:
            raise ValueError(
                "Logistic regression requires both target classes in train."
            )

        x_train = self._feature_frame(train_df)
        self.medians_ = x_train.median(numeric_only=True).fillna(0.0)
        x_imputed = x_train.fillna(self.medians_)
        self.means_ = x_imputed.mean(numeric_only=True)
        self.stds_ = x_imputed.std(ddof=0).replace(0.0, 1.0).fillna(1.0)
        x_scaled = (x_imputed - self.means_) / self.stds_

        model = LogisticRegression(max_iter=1000, random_state=0)
        model.fit(x_scaled.to_numpy(dtype=float), y.to_numpy(dtype=int))
        self.model_ = model
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        if (
            self.model_ is None
            or self.medians_ is None
            or self.means_ is None
            or self.stds_ is None
        ):
            raise ValueError("LogisticRegressionBaseline must be fit first.")
        x = self._feature_frame(df)
        x_scaled = (x.fillna(self.medians_) - self.means_) / self.stds_
        return self.model_.predict_proba(x_scaled.to_numpy(dtype=float))[:, 1]

    def _feature_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        missing = [column for column in self.feature_columns if column not in df]
        if missing:
            raise ValueError(
                "Training examples missing feature columns: "
                + ", ".join(missing)
            )
        return df.loc[:, self.feature_columns].apply(
            pd.to_numeric,
            errors="coerce",
        )
