from __future__ import annotations

import inspect
from datetime import date, timedelta

import pandas as pd
import pytest

import ml.backtest as backtest
from ml.backtest import (
    BacktestError,
    chronological_split,
    run_batter_hits_baseline_backtest,
)
from ml.data import FEATURE_COLUMNS


def test_chronological_split_preserves_time_order() -> None:
    df = _examples(20).sample(frac=1.0, random_state=42)

    splits = chronological_split(df)

    assert splits.strategy == "chronological_70_15_15"
    assert splits.train["game_date"].max() <= splits.validation["game_date"].min()
    assert splits.validation["game_date"].max() <= splits.test["game_date"].min()
    assert [len(splits.train), len(splits.validation), len(splits.test)] == [
        14,
        3,
        3,
    ]


def test_backtest_module_does_not_use_random_split() -> None:
    source = inspect.getsource(backtest)

    assert "train_test_split" not in source
    assert "random_split" not in source


def test_backtest_writes_report_with_both_models(tmp_path) -> None:
    summary = run_batter_hits_baseline_backtest(
        examples_df=_examples(30),
        output_dir=tmp_path,
        min_examples=20,
    )

    assert summary.report_path.exists()
    assert summary.report["models_evaluated"] == [
        "global_positive_rate",
        "rule_based_hit_rate",
        "logistic_regression",
    ]
    assert summary.report["warnings"] == [
        "Test split has 5 slate(s); fewer than 30 test slates is a smoke test only."
    ]
    assert summary.report["slate_summary"]["test"]["number_of_slates"] == 5
    assert "validation" in summary.report["top_k_daily_metrics"][
        "rule_based_hit_rate"
    ]


def test_backtest_fails_clearly_when_too_few_examples(tmp_path) -> None:
    with pytest.raises(BacktestError, match="Too few"):
        run_batter_hits_baseline_backtest(
            examples_df=_examples(5),
            output_dir=tmp_path,
            min_examples=20,
        )


def test_manual_split_requires_both_boundaries() -> None:
    with pytest.raises(BacktestError, match="provided together"):
        chronological_split(_examples(20), train_end_date=date(2026, 6, 10))


def _examples(count: int) -> pd.DataFrame:
    start = date(2026, 6, 1)
    rows: list[dict[str, object]] = []
    for index in range(count):
        row: dict[str, object] = {
            "id": index + 1,
            "game_date": start + timedelta(days=index),
            "commence_time": pd.Timestamp(start + timedelta(days=index)),
            "target_over": index % 2 == 0,
            "actual_hits": 1 if index % 2 == 0 else 0,
            "feature_version": "rolling-batter-hits-v2",
        }
        for feature_index, column in enumerate(FEATURE_COLUMNS):
            row[column] = float((index + feature_index) % 5) / 4
        row["line"] = 0.5 if index % 2 == 0 else 1.5
        row["hit_rate_last_10"] = 0.65 if index % 2 == 0 else 0.35
        row["season_hit_rate_before"] = 0.55 if index % 2 == 0 else 0.45
        rows.append(row)
    return pd.DataFrame(rows)
