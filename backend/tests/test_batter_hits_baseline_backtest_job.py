from __future__ import annotations

from pathlib import Path
from typing import Any

from ml.backtest import BacktestError, BacktestSummary
from jobs import backtest_batter_hits_baselines as job


def test_cli_passes_arguments_and_prints_summary(monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(**kwargs: object) -> BacktestSummary:
        calls.append(kwargs)
        return BacktestSummary(
            report_path=Path("artifacts/backtests/report.json"),
            elapsed_seconds=1.2345,
            report={
                "date_range_used": {
                    "start_date": "2026-06-01",
                    "end_date": "2026-06-30",
                },
                "split_strategy": "chronological_70_15_15",
                "warnings": [
                    "Test split has 5 slate(s); fewer than 30 test slates is a smoke test only."
                ],
                "splits": {
                    "train": {
                        "examples": 70,
                        "start_date": "2026-06-01",
                        "end_date": "2026-06-20",
                    },
                    "validation": {
                        "examples": 15,
                        "start_date": "2026-06-21",
                        "end_date": "2026-06-25",
                    },
                    "test": {
                        "examples": 15,
                        "start_date": "2026-06-26",
                        "end_date": "2026-06-30",
                    },
                },
                "slate_summary": {
                    "train": _slate_summary(20),
                    "validation": _slate_summary(5),
                    "test": _slate_summary(5),
                },
                "metrics_by_split": {
                    "global_positive_rate": _split_metrics(),
                    "rule_based_hit_rate": _split_metrics(),
                    "logistic_regression": _split_metrics(),
                },
                "top_k_daily_metrics": {
                    "global_positive_rate": {
                        "validation": _top_metrics(),
                        "test": _top_metrics(),
                    },
                    "rule_based_hit_rate": {
                        "validation": _top_metrics(),
                        "test": _top_metrics(),
                    },
                    "logistic_regression": {
                        "validation": _top_metrics(),
                        "test": _top_metrics(),
                    },
                },
            },
        )

    monkeypatch.setattr(job, "run_batter_hits_baseline_backtest", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "jobs.backtest_batter_hits_baselines",
            "--start-date",
            "2026-06-01",
            "--end-date",
            "2026-06-30",
            "--train-end-date",
            "2026-06-20",
            "--test-start-date",
            "2026-06-26",
            "--min-prior-games",
            "5",
            "--limit",
            "100",
            "--output-dir",
            "custom/backtests",
        ],
    )

    result = job.main()

    assert result == 0
    assert calls == [
        {
            "start_date": __import__("datetime").date(2026, 6, 1),
            "end_date": __import__("datetime").date(2026, 6, 30),
            "train_end_date": __import__("datetime").date(2026, 6, 20),
            "test_start_date": __import__("datetime").date(2026, 6, 26),
            "min_prior_games": 5,
            "limit": 100,
            "output_dir": Path("custom/backtests"),
        }
    ]
    output = capsys.readouterr().out
    assert "Batter hits baseline backtest" in output
    assert "WARNING: Test split has 5 slate" in output
    assert "global_positive_rate" in output


def test_cli_reports_backtest_errors(monkeypatch, capsys) -> None:
    def fake_run(**_kwargs: object) -> BacktestSummary:
        raise BacktestError("Too few batter hits training examples")

    monkeypatch.setattr(job, "run_batter_hits_baseline_backtest", fake_run)
    monkeypatch.setattr("sys.argv", ["jobs.backtest_batter_hits_baselines"])

    result = job.main()

    assert result == 1
    assert "Too few batter hits" in capsys.readouterr().err


def _split_metrics() -> dict[str, dict[str, Any]]:
    metrics = {
        "examples": 1,
        "accuracy_at_0_5": 1.0,
        "log_loss": 0.1,
        "brier_score": 0.01,
        "roc_auc": None,
    }
    return {
        "train": metrics,
        "validation": metrics,
        "test": metrics,
    }


def _top_metrics() -> dict[str, object]:
    return {
        "number_of_slates": 1,
        "top_1_hit_rate": 1.0,
        "top_3_hit_rate": 0.67,
        "top_5_hit_rate": 0.6,
        "top_10_hit_rate": 0.55,
    }


def _slate_summary(slates: int) -> dict[str, object]:
    return {
        "number_of_slates": slates,
        "average_candidates_per_slate": 3.0,
    }
