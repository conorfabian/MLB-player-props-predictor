from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, cast

from app.settings import SettingsError
from ml.backtest import BacktestError, run_batter_hits_baseline_backtest

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--train-end-date")
    parser.add_argument("--test-start-date")
    parser.add_argument("--min-prior-games", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--output-dir",
        default="artifacts/backtests",
        type=Path,
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        summary = run_batter_hits_baseline_backtest(
            start_date=_optional_date(args.start_date),
            end_date=_optional_date(args.end_date),
            train_end_date=_optional_date(args.train_end_date),
            test_start_date=_optional_date(args.test_start_date),
            min_prior_games=args.min_prior_games,
            limit=args.limit,
            output_dir=args.output_dir,
        )
    except (BacktestError, SettingsError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        logger.exception("Batter hits baseline backtest failed")
        return 1

    _print_summary(summary.report, summary.report_path, summary.elapsed_seconds)
    return 0


def _optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def _print_summary(
    report: dict[str, Any],
    report_path: Path,
    elapsed_seconds: float,
) -> None:
    print("Batter hits baseline backtest")
    print(f"Report: {report_path}")
    print(f"Date range: {_range_text(report['date_range_used'])}")
    print(f"Split strategy: {report['split_strategy']}")
    for warning in report.get("warnings", []):
        print(f"WARNING: {warning}")
    for split_name, split in report["splits"].items():
        slate_summary = report["slate_summary"][split_name]
        print(
            "{name}: examples={examples} slates={slates} "
            "avg_candidates_per_slate={avg_candidates} dates={dates}".format(
                name=split_name,
                examples=split["examples"],
                slates=slate_summary["number_of_slates"],
                avg_candidates=_optional_rate(
                    slate_summary["average_candidates_per_slate"]
                ),
                dates=_range_text(split),
            )
        )

    for model_name, split_metrics in report["metrics_by_split"].items():
        print(f"\n{model_name}")
        for split_name in ("train", "validation", "test"):
            metrics = split_metrics[split_name]
            roc_auc = metrics["roc_auc"]
            print(
                "  {split}: examples={examples} accuracy={accuracy:.3f} "
                "log_loss={log_loss:.3f} brier={brier:.3f} "
                "roc_auc={roc_auc}".format(
                    split=split_name,
                    examples=metrics["examples"],
                    accuracy=metrics["accuracy_at_0_5"],
                    log_loss=metrics["log_loss"],
                    brier=metrics["brier_score"],
                    roc_auc=(
                        "n/a" if roc_auc is None else f"{roc_auc:.3f}"
                    ),
                )
            )
        for split_name in ("validation", "test"):
            top_metrics = report["top_k_daily_metrics"][model_name][split_name]
            print(
                "  {split} top-k: slates={slates} top1={top1} "
                "top3={top3} top5={top5} top10={top10}".format(
                    split=split_name,
                    slates=top_metrics["number_of_slates"],
                    top1=_optional_rate(top_metrics["top_1_hit_rate"]),
                    top3=_optional_rate(top_metrics["top_3_hit_rate"]),
                    top5=_optional_rate(top_metrics["top_5_hit_rate"]),
                    top10=_optional_rate(top_metrics["top_10_hit_rate"]),
                )
            )

    print(f"\nelapsed_seconds={elapsed_seconds:.3f}")


def _range_text(value: dict[str, Any]) -> str:
    return f"{value['start_date']}..{value['end_date']}"


def _optional_rate(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{float(cast(float, value)):.3f}"


if __name__ == "__main__":
    sys.exit(main())
