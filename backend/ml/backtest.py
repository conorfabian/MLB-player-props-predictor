from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

import pandas as pd
from supabase import Client

from ml.baselines import (
    GlobalPositiveRateBaseline,
    LogisticRegressionBaseline,
    RuleBasedHitRateBaseline,
)
from ml.data import (
    DATE_COLUMN,
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    load_batter_hits_training_examples,
    validate_feature_columns,
)
from ml.metrics import (
    binary_classification_metrics,
    calibration_table,
    daily_top_k_metrics,
)

DEFAULT_MIN_EXAMPLES = 20
MIN_RELIABLE_TEST_SLATES = 30


class BacktestError(RuntimeError):
    pass


class BaselineModel(Protocol):
    name: str

    def fit(self, train_df: pd.DataFrame) -> "BaselineModel":
        ...

    def predict_proba(self, df: pd.DataFrame) -> Any:
        ...


@dataclass(frozen=True)
class SplitFrames:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    strategy: str


@dataclass(frozen=True)
class BacktestSummary:
    report_path: Path
    report: dict[str, Any]
    elapsed_seconds: float


def run_batter_hits_baseline_backtest(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    train_end_date: date | None = None,
    test_start_date: date | None = None,
    min_prior_games: int = 0,
    limit: int | None = None,
    output_dir: Path | str = Path("artifacts/backtests"),
    min_examples: int = DEFAULT_MIN_EXAMPLES,
    supabase: Client | None = None,
    examples_df: pd.DataFrame | None = None,
) -> BacktestSummary:
    started = perf_counter()
    _validate_args(
        start_date=start_date,
        end_date=end_date,
        train_end_date=train_end_date,
        test_start_date=test_start_date,
        min_prior_games=min_prior_games,
        limit=limit,
    )
    feature_columns = validate_feature_columns(FEATURE_COLUMNS)
    df = (
        examples_df.copy()
        if examples_df is not None
        else load_batter_hits_training_examples(
            start_date=start_date,
            end_date=end_date,
            min_prior_games=min_prior_games,
            limit=limit,
            supabase=supabase,
        )
    )
    df = _prepare_examples(df)
    if len(df) < min_examples:
        raise BacktestError(
            "Too few batter hits training examples after filtering: "
            f"{len(df)} found, need at least {min_examples}."
        )

    splits = chronological_split(
        df,
        train_end_date=train_end_date,
        test_start_date=test_start_date,
    )
    _validate_splits(splits)

    models: list[BaselineModel] = [
        GlobalPositiveRateBaseline(),
        RuleBasedHitRateBaseline(),
        LogisticRegressionBaseline(feature_columns=feature_columns),
    ]
    metrics_by_split: dict[str, dict[str, Any]] = {}
    top_k_metrics: dict[str, dict[str, Any]] = {}
    calibration: dict[str, dict[str, Any]] = {}

    for model in models:
        try:
            model.fit(splits.train)
        except ValueError as exc:
            raise BacktestError(f"{model.name} training failed: {exc}") from exc

        metrics_by_split[model.name] = {}
        top_k_metrics[model.name] = {}
        calibration[model.name] = {}
        for split_name in ("train", "validation", "test"):
            split_df = getattr(splits, split_name)
            y_prob = model.predict_proba(split_df)
            y_true = split_df[TARGET_COLUMN].astype(int)
            metrics_by_split[model.name][split_name] = (
                binary_classification_metrics(y_true, y_prob)
            )
            calibration[model.name][split_name] = calibration_table(
                y_true,
                y_prob,
            )
            if split_name in {"validation", "test"}:
                top_k_metrics[model.name][split_name] = daily_top_k_metrics(
                    split_df,
                    y_prob,
                )

    generated_at = datetime.now(UTC)
    report = {
        "generated_at": generated_at.isoformat(),
        "date_range_used": _date_range(df),
        "split_strategy": splits.strategy,
        "splits": {
            "train": _split_metadata(splits.train),
            "validation": _split_metadata(splits.validation),
            "test": _split_metadata(splits.test),
        },
        "feature_version": _feature_version(df),
        "models_evaluated": [model.name for model in models],
        "feature_columns": list(feature_columns),
        "slate_summary": {
            "train": slate_summary(splits.train),
            "validation": slate_summary(splits.validation),
            "test": slate_summary(splits.test),
        },
        "warnings": _warnings(splits),
        "metrics_by_split": metrics_by_split,
        "top_k_daily_metrics": top_k_metrics,
        "calibration_tables": calibration,
        "limitations_todos": [
            "Offline baseline only; production daily board scoring unchanged.",
            "Logistic regression uses stored pre-game numeric features only.",
            "Future PyTorch models should beat these validation/test metrics.",
        ],
    }
    report_path = _write_report(
        report,
        output_dir=Path(output_dir),
        generated_at=generated_at,
    )
    return BacktestSummary(
        report_path=report_path,
        report=report,
        elapsed_seconds=perf_counter() - started,
    )


def chronological_split(
    df: pd.DataFrame,
    *,
    train_end_date: date | None = None,
    test_start_date: date | None = None,
) -> SplitFrames:
    sorted_df = _sort_chronologically(df)
    if train_end_date is not None or test_start_date is not None:
        if train_end_date is None or test_start_date is None:
            raise BacktestError(
                "--train-end-date and --test-start-date must be provided "
                "together."
            )
        if train_end_date >= test_start_date:
            raise BacktestError(
                "--train-end-date must be before --test-start-date."
            )
        return SplitFrames(
            train=sorted_df[sorted_df[DATE_COLUMN] <= train_end_date].copy(),
            validation=sorted_df[
                (sorted_df[DATE_COLUMN] > train_end_date)
                & (sorted_df[DATE_COLUMN] < test_start_date)
            ].copy(),
            test=sorted_df[sorted_df[DATE_COLUMN] >= test_start_date].copy(),
            strategy="manual_chronological_date_boundaries",
        )

    train_end = int(len(sorted_df) * 0.70)
    validation_end = int(len(sorted_df) * 0.85)
    return SplitFrames(
        train=sorted_df.iloc[:train_end].copy(),
        validation=sorted_df.iloc[train_end:validation_end].copy(),
        test=sorted_df.iloc[validation_end:].copy(),
        strategy="chronological_70_15_15",
    )


def slate_summary(df: pd.DataFrame) -> dict[str, float | int | None]:
    if df.empty:
        return {
            "number_of_slates": 0,
            "total_candidates": 0,
            "average_candidates_per_slate": None,
            "median_candidates_per_slate": None,
            "min_candidates_per_slate": None,
            "max_candidates_per_slate": None,
            "average_slate_actual_rate": None,
            "overall_actual_rate": None,
        }
    slate_sizes = df.groupby(DATE_COLUMN).size()
    slate_actual_rates = df.groupby(DATE_COLUMN)[TARGET_COLUMN].mean()
    return {
        "number_of_slates": int(slate_sizes.size),
        "total_candidates": int(len(df)),
        "average_candidates_per_slate": float(slate_sizes.mean()),
        "median_candidates_per_slate": float(slate_sizes.median()),
        "min_candidates_per_slate": int(slate_sizes.min()),
        "max_candidates_per_slate": int(slate_sizes.max()),
        "average_slate_actual_rate": float(slate_actual_rates.mean()),
        "overall_actual_rate": float(df[TARGET_COLUMN].astype(int).mean()),
    }


def _prepare_examples(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    missing = [
        column
        for column in (DATE_COLUMN, TARGET_COLUMN, *FEATURE_COLUMNS)
        if column not in df
    ]
    if missing:
        raise BacktestError(
            "Training examples missing required columns: "
            + ", ".join(missing)
        )
    prepared = df.copy()
    prepared[DATE_COLUMN] = pd.to_datetime(prepared[DATE_COLUMN]).dt.date
    prepared[TARGET_COLUMN] = prepared[TARGET_COLUMN].astype(bool)
    for column in FEATURE_COLUMNS:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    return _sort_chronologically(prepared)


def _sort_chronologically(df: pd.DataFrame) -> pd.DataFrame:
    sort_columns = [DATE_COLUMN]
    if "commence_time" in df:
        sort_columns.append("commence_time")
    if "id" in df:
        sort_columns.append("id")
    return df.sort_values(sort_columns).reset_index(drop=True)


def _validate_args(
    *,
    start_date: date | None,
    end_date: date | None,
    train_end_date: date | None,
    test_start_date: date | None,
    min_prior_games: int,
    limit: int | None,
) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise BacktestError("--start-date must be before or equal to --end-date.")
    if (train_end_date is None) != (test_start_date is None):
        raise BacktestError(
            "--train-end-date and --test-start-date must be provided together."
        )
    if (
        train_end_date is not None
        and test_start_date is not None
        and train_end_date >= test_start_date
    ):
        raise BacktestError("--train-end-date must be before --test-start-date.")
    if min_prior_games < 0:
        raise BacktestError("--min-prior-games must be zero or greater.")
    if limit is not None and limit <= 0:
        raise BacktestError("--limit must be positive.")


def _validate_splits(splits: SplitFrames) -> None:
    sizes = {
        "train": len(splits.train),
        "validation": len(splits.validation),
        "test": len(splits.test),
    }
    empty = [name for name, size in sizes.items() if size == 0]
    if empty:
        raise BacktestError(
            "Chronological split produced empty split(s): "
            + ", ".join(empty)
            + ". Provide a wider date range or different split dates."
        )


def _warnings(splits: SplitFrames) -> list[str]:
    test_slates = int(splits.test[DATE_COLUMN].nunique())
    if test_slates < MIN_RELIABLE_TEST_SLATES:
        return [
            "Test split has "
            f"{test_slates} slate(s); fewer than "
            f"{MIN_RELIABLE_TEST_SLATES} test slates is a smoke test only."
        ]
    return []


def _date_range(df: pd.DataFrame) -> dict[str, str | None]:
    if df.empty:
        return {"start_date": None, "end_date": None}
    return {
        "start_date": df[DATE_COLUMN].min().isoformat(),
        "end_date": df[DATE_COLUMN].max().isoformat(),
    }


def _split_metadata(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "examples": int(len(df)),
        **_date_range(df),
    }


def _feature_version(df: pd.DataFrame) -> str | list[str] | None:
    if "feature_version" not in df or df.empty:
        return None
    versions = sorted(str(item) for item in df["feature_version"].dropna().unique())
    if len(versions) == 1:
        return versions[0]
    return versions


def _write_report(
    report: dict[str, Any],
    *,
    output_dir: Path,
    generated_at: datetime,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        generated_at.strftime("%Y%m%d_%H%M%S")
        + "_batter_hits_baselines.json"
    )
    path = output_dir / filename
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return path
