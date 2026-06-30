from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

from supabase import Client

from app.db import get_supabase
from app.repositories import get_batter_hits_training_example_health_rows

NULLABLE_FEATURE_COLUMNS = (
    "hit_rate_last_3",
    "hit_rate_last_5",
    "hit_rate_last_10",
    "avg_hits_last_10",
    "avg_at_bats_last_10",
    "avg_plate_appearances_last_10",
    "avg_total_bases_last_10",
    "strikeout_rate_last_10",
    "walk_rate_last_10",
    "season_hit_rate_before",
    "season_avg_hits_before",
)


def get_batter_hits_dataset_health(
    *,
    supabase: Client | None = None,
) -> dict[str, Any]:
    supabase = supabase or get_supabase()
    rows = get_batter_hits_training_example_health_rows(supabase)
    return batter_hits_dataset_health_from_rows(rows)


def batter_hits_dataset_health_from_rows(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    total_examples = len(rows)
    null_feature_counts = {
        column: sum(1 for row in rows if row.get(column) is None)
        for column in NULLABLE_FEATURE_COLUMNS
    }

    if total_examples == 0:
        return {
            "total_examples": 0,
            "total_slates": 0,
            "date_range": {
                "start_date": None,
                "end_date": None,
            },
            "latest_slate_date": None,
            "examples_per_slate": None,
            "target_over_positive_rate": None,
            "line_distribution": {},
            "cold_start_count": 0,
            "cold_start_rate": None,
            "null_feature_counts": null_feature_counts,
            "status": "smoke_test_only",
        }

    slate_dates = [_parse_date(row["game_date"]) for row in rows]
    unique_slates = set(slate_dates)
    total_slates = len(unique_slates)
    target_over_count = sum(1 for row in rows if row.get("target_over") is True)
    cold_start_count = sum(1 for row in rows if row.get("is_cold_start") is True)
    line_counts = Counter(float(row["line"]) for row in rows)

    return {
        "total_examples": total_examples,
        "total_slates": total_slates,
        "date_range": {
            "start_date": min(slate_dates).isoformat(),
            "end_date": max(slate_dates).isoformat(),
        },
        "latest_slate_date": max(slate_dates).isoformat(),
        "examples_per_slate": total_examples / total_slates,
        "target_over_positive_rate": target_over_count / total_examples,
        "line_distribution": {
            _line_key(line): line_counts[line]
            for line in sorted(line_counts)
        },
        "cold_start_count": cold_start_count,
        "cold_start_rate": cold_start_count / total_examples,
        "null_feature_counts": null_feature_counts,
        "status": _status(total_slates),
    }


def _status(total_slates: int) -> str:
    if total_slates < 30:
        return "smoke_test_only"
    if total_slates < 100:
        return "early_but_usable"
    return "more_stable"


def _parse_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _line_key(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)
