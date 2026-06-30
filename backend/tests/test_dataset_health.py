from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import main
from app.dataset_health import (
    NULLABLE_FEATURE_COLUMNS,
    batter_hits_dataset_health_from_rows,
)


def test_batter_hits_dataset_health_empty_dataset() -> None:
    report = batter_hits_dataset_health_from_rows([])

    assert report == {
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
        "null_feature_counts": {
            column: 0 for column in NULLABLE_FEATURE_COLUMNS
        },
        "status": "smoke_test_only",
    }


def test_batter_hits_dataset_health_computes_smoke_test_metrics() -> None:
    rows = [
        _row(
            game_date="2026-06-01",
            target_over=True,
            line=1.5,
            is_cold_start=True,
            hit_rate_last_3=None,
            avg_hits_last_10=None,
        ),
        _row(
            game_date="2026-06-02",
            target_over=False,
            line=0.5,
            is_cold_start=False,
            season_hit_rate_before=None,
        ),
        _row(
            game_date="2026-06-02",
            target_over=True,
            line=0.5,
            is_cold_start=True,
            walk_rate_last_10=None,
        ),
    ]

    report = batter_hits_dataset_health_from_rows(rows)

    assert report["total_examples"] == 3
    assert report["total_slates"] == 2
    assert report["date_range"] == {
        "start_date": "2026-06-01",
        "end_date": "2026-06-02",
    }
    assert report["latest_slate_date"] == "2026-06-02"
    assert report["examples_per_slate"] == 1.5
    assert report["target_over_positive_rate"] == 2 / 3
    assert report["line_distribution"] == {
        "0.5": 2,
        "1.5": 1,
    }
    assert report["cold_start_count"] == 2
    assert report["cold_start_rate"] == 2 / 3
    assert report["null_feature_counts"]["hit_rate_last_3"] == 1
    assert report["null_feature_counts"]["avg_hits_last_10"] == 1
    assert report["null_feature_counts"]["season_hit_rate_before"] == 1
    assert report["null_feature_counts"]["walk_rate_last_10"] == 1
    assert report["status"] == "smoke_test_only"


def test_batter_hits_dataset_health_status_thresholds() -> None:
    early_rows = [
        _row(game_date=(date(2026, 6, 1) + timedelta(days=offset)).isoformat())
        for offset in range(30)
    ]
    stable_rows = [
        _row(game_date=(date(2026, 6, 1) + timedelta(days=offset)).isoformat())
        for offset in range(100)
    ]

    assert (
        batter_hits_dataset_health_from_rows(early_rows)["status"]
        == "early_but_usable"
    )
    assert (
        batter_hits_dataset_health_from_rows(stable_rows)["status"]
        == "more_stable"
    )


def test_dataset_health_endpoint_returns_report(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "get_batter_hits_dataset_health",
        lambda: {"status": "smoke_test_only", "total_examples": 0},
    )
    client = TestClient(main.app)

    response = client.get("/api/dataset-health/batter-hits")

    assert response.status_code == 200
    assert response.json() == {
        "status": "smoke_test_only",
        "total_examples": 0,
    }


def _row(
    *,
    game_date: str = "2026-06-01",
    target_over: bool = True,
    line: float = 0.5,
    is_cold_start: bool = False,
    **overrides: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "game_date": game_date,
        "target_over": target_over,
        "line": line,
        "is_cold_start": is_cold_start,
        "hit_rate_last_3": 1.0,
        "hit_rate_last_5": 1.0,
        "hit_rate_last_10": 1.0,
        "avg_hits_last_10": 1.0,
        "avg_at_bats_last_10": 4.0,
        "avg_plate_appearances_last_10": 4.0,
        "avg_total_bases_last_10": 1.0,
        "strikeout_rate_last_10": 0.25,
        "walk_rate_last_10": 0.1,
        "season_hit_rate_before": 1.0,
        "season_avg_hits_before": 1.0,
    }
    row.update(overrides)
    return row
