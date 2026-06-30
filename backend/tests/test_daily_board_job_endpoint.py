from __future__ import annotations

from datetime import date
from threading import Lock

from fastapi.testclient import TestClient

from app import main
from app.domain import FeatureBuildSummary
from app.grading import GradingSummary
from app.pipeline import (
    BoardGenerationSummary,
    DailyBoardJobSummary,
    IngestionSummary,
)
from app.player_game_batting import PlayerGameBattingBackfillSummary
from app.settings import Settings


def _settings(*, cron_job_secret: str = "cron-secret") -> Settings:
    return Settings(
        supabase_url="https://example.supabase.co",
        supabase_secret_key="secret",
        frontend_origins=("http://localhost:3000",),
        propline_api_key="api-secret",
        propline_base_url="https://api.prop-line.com/v1",
        propline_timeout_seconds=30,
        slate_timezone="America/New_York",
        cron_job_secret=cron_job_secret,
    )


def _summary() -> DailyBoardJobSummary:
    return DailyBoardJobSummary(
        ingestion=IngestionSummary(
            run_id="ingest-1",
            events_found=2,
            events_processed=2,
            offers_normalized=12,
            offers_saved=12,
            skipped_non_prizepicks=1,
            skipped_nonstandard_dfs=2,
            skipped_malformed=3,
            elapsed_seconds=1.2345,
            candidates=[],
        ),
        board=BoardGenerationSummary(
            slate_date=date(2026, 6, 26),
            ingestion_run_id="ingest-1",
            candidates=12,
            published=10,
            model_version="placeholder-v0",
            elapsed_seconds=2.3456,
            top_picks=[],
        ),
    )


def _player_game_batting_summary() -> PlayerGameBattingBackfillSummary:
    return PlayerGameBattingBackfillSummary(
        events_found=4,
        events_processed=3,
        player_rows_parsed=27,
        player_rows_upserted=27,
        skipped_events=1,
        skipped_players=2,
        elapsed_seconds=1.2345,
    )


def _feature_build_summary(
    *,
    examples_upserted: int = 6,
) -> FeatureBuildSummary:
    return FeatureBuildSummary(
        candidates_found=10,
        candidates_deduped=8,
        examples_built=7,
        examples_upserted=examples_upserted,
        skipped_missing_label=1,
        skipped_missing_history=0,
        skipped_unsupported_side=2,
        elapsed_seconds=1.2345,
    )


def test_daily_board_job_requires_auth(monkeypatch) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post("/api/jobs/daily-board")

    assert response.status_code == 401


def test_daily_board_job_rejects_wrong_auth(monkeypatch) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/daily-board",
        headers={"Authorization": "Bearer wrong-secret"},
    )

    assert response.status_code == 401


def test_daily_board_job_requires_configured_secret(monkeypatch) -> None:
    monkeypatch.setattr(main, "settings", _settings(cron_job_secret=""))
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/daily-board",
        headers={"Authorization": "Bearer anything"},
    )

    assert response.status_code == 503


def test_daily_board_job_rejects_overlapping_run(monkeypatch) -> None:
    lock = Lock()
    assert lock.acquire(blocking=False)
    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setattr(main, "job_lock", lock)
    client = TestClient(main.app)

    try:
        response = client.post(
            "/api/jobs/daily-board",
            headers={"Authorization": "Bearer cron-secret"},
        )
    finally:
        lock.release()

    assert response.status_code == 409


def test_daily_board_job_returns_summary(monkeypatch) -> None:
    calls = 0

    def fake_job() -> DailyBoardJobSummary:
        nonlocal calls
        calls += 1
        return _summary()

    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setattr(main, "job_lock", Lock())
    monkeypatch.setattr(main, "run_daily_board_job", fake_job)
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/daily-board",
        headers={"Authorization": "Bearer cron-secret"},
    )

    assert response.status_code == 200
    assert calls == 1
    assert response.json() == {
        "status": "completed",
        "ingestion": {
            "run_id": "ingest-1",
            "events_found": 2,
            "events_processed": 2,
            "offers_normalized": 12,
            "offers_saved": 12,
            "skipped_non_prizepicks": 1,
            "skipped_nonstandard_dfs": 2,
            "skipped_malformed": 3,
            "elapsed_seconds": 1.234,
        },
        "board": {
            "slate_date": "2026-06-26",
            "ingestion_run_id": "ingest-1",
            "candidates": 12,
            "published": 10,
            "model_version": "placeholder-v0",
            "elapsed_seconds": 2.346,
        },
    }


def test_grade_board_job_requires_auth(monkeypatch) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post("/api/jobs/grade-board")

    assert response.status_code == 401


def test_grade_board_job_rejects_overlapping_run(monkeypatch) -> None:
    lock = Lock()
    assert lock.acquire(blocking=False)
    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setattr(main, "grading_job_lock", lock)
    client = TestClient(main.app)

    try:
        response = client.post(
            "/api/jobs/grade-board",
            headers={"Authorization": "Bearer cron-secret"},
        )
    finally:
        lock.release()

    assert response.status_code == 409


def test_grade_board_job_returns_summary(monkeypatch) -> None:
    calls = 0

    def fake_job() -> GradingSummary:
        nonlocal calls
        calls += 1
        return GradingSummary(
            graded=3,
            still_pending=2,
            hits=1,
            misses=1,
            pushes=1,
            skipped=2,
            elapsed_seconds=1.2345,
        )

    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setattr(main, "grading_job_lock", Lock())
    monkeypatch.setattr(main, "run_board_grading", fake_job)
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/grade-board",
        headers={"Authorization": "Bearer cron-secret"},
    )

    assert response.status_code == 200
    assert calls == 1
    assert response.json() == {
        "status": "completed",
        "graded": 3,
        "still_pending": 2,
        "hits": 1,
        "misses": 1,
        "pushes": 1,
        "skipped": 2,
        "elapsed_seconds": 1.234,
    }


def test_backfill_player_game_batting_requires_auth(monkeypatch) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post("/api/jobs/backfill-player-game-batting")

    assert response.status_code == 401


def test_backfill_player_game_batting_rejects_wrong_auth(monkeypatch) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/backfill-player-game-batting",
        headers={"Authorization": "Bearer wrong-secret"},
    )

    assert response.status_code == 401


def test_backfill_player_game_batting_rejects_overlapping_run(
    monkeypatch,
) -> None:
    lock = Lock()
    assert lock.acquire(blocking=False)
    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setattr(main, "player_game_batting_job_lock", lock)
    client = TestClient(main.app)

    try:
        response = client.post(
            "/api/jobs/backfill-player-game-batting",
            headers={"Authorization": "Bearer cron-secret"},
        )
    finally:
        lock.release()

    assert response.status_code == 409


def test_backfill_player_game_batting_empty_body_uses_default_window(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_job(**kwargs: object) -> PlayerGameBattingBackfillSummary:
        calls.append(kwargs)
        return _player_game_batting_summary()

    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setattr(main, "player_game_batting_job_lock", Lock())
    monkeypatch.setattr(main, "run_player_game_batting_backfill", fake_job)
    monkeypatch.setattr(
        main,
        "_current_slate_date",
        lambda: date(2026, 6, 26),
    )
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/backfill-player-game-batting",
        headers={"Authorization": "Bearer cron-secret"},
        json={},
    )

    assert response.status_code == 200
    assert calls == [
        {
            "dry_run": False,
            "slate_date": None,
            "start_date": date(2026, 6, 25),
            "end_date": date(2026, 6, 26),
            "limit_events": 50,
        }
    ]
    assert response.json() == {
        "status": "completed",
        "resolved_window": {
            "slate_date": None,
            "start_date": "2026-06-25",
            "end_date": "2026-06-26",
            "limit_events": 50,
            "dry_run": False,
        },
        "events_found": 4,
        "events_processed": 3,
        "player_rows_parsed": 27,
        "player_rows_upserted": 27,
        "skipped_events": 1,
        "skipped_players": 2,
        "elapsed_seconds": 1.234,
    }


def test_backfill_player_game_batting_passes_explicit_slate_date(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_job(**kwargs: object) -> PlayerGameBattingBackfillSummary:
        calls.append(kwargs)
        return _player_game_batting_summary()

    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setattr(main, "player_game_batting_job_lock", Lock())
    monkeypatch.setattr(main, "run_player_game_batting_backfill", fake_job)
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/backfill-player-game-batting",
        headers={"Authorization": "Bearer cron-secret"},
        json={
            "slate_date": "2026-06-24",
            "limit_events": 12,
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    assert calls == [
        {
            "dry_run": True,
            "slate_date": date(2026, 6, 24),
            "start_date": None,
            "end_date": None,
            "limit_events": 12,
        }
    ]
    assert response.json()["resolved_window"] == {
        "slate_date": "2026-06-24",
        "start_date": None,
        "end_date": None,
        "limit_events": 12,
        "dry_run": True,
    }


def test_backfill_player_game_batting_passes_explicit_date_range(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_job(**kwargs: object) -> PlayerGameBattingBackfillSummary:
        calls.append(kwargs)
        return _player_game_batting_summary()

    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setattr(main, "player_game_batting_job_lock", Lock())
    monkeypatch.setattr(main, "run_player_game_batting_backfill", fake_job)
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/backfill-player-game-batting",
        headers={"Authorization": "Bearer cron-secret"},
        json={
            "start_date": "2026-06-20",
            "end_date": "2026-06-22",
            "limit_events": 100,
        },
    )

    assert response.status_code == 200
    assert calls == [
        {
            "dry_run": False,
            "slate_date": None,
            "start_date": date(2026, 6, 20),
            "end_date": date(2026, 6, 22),
            "limit_events": 100,
        }
    ]
    assert response.json()["resolved_window"] == {
        "slate_date": None,
        "start_date": "2026-06-20",
        "end_date": "2026-06-22",
        "limit_events": 100,
        "dry_run": False,
    }


def test_backfill_player_game_batting_rejects_invalid_date_combination(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/backfill-player-game-batting",
        headers={"Authorization": "Bearer cron-secret"},
        json={
            "slate_date": "2026-06-24",
            "start_date": "2026-06-20",
            "end_date": "2026-06-22",
        },
    )

    assert response.status_code == 422


def test_backfill_player_game_batting_rejects_invalid_range_order(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/backfill-player-game-batting",
        headers={"Authorization": "Bearer cron-secret"},
        json={
            "start_date": "2026-06-22",
            "end_date": "2026-06-20",
        },
    )

    assert response.status_code == 422


def test_backfill_player_game_batting_rejects_limit_above_cap(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/backfill-player-game-batting",
        headers={"Authorization": "Bearer cron-secret"},
        json={"limit_events": 101},
    )

    assert response.status_code == 422


def test_build_batter_hits_training_examples_requires_auth(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post("/api/jobs/build-batter-hits-training-examples")

    assert response.status_code == 401


def test_build_batter_hits_training_examples_rejects_wrong_auth(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/build-batter-hits-training-examples",
        headers={"Authorization": "Bearer wrong-secret"},
    )

    assert response.status_code == 401


def test_build_batter_hits_training_examples_empty_body_uses_default_window(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_job(**kwargs: object) -> FeatureBuildSummary:
        calls.append(kwargs)
        return _feature_build_summary()

    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setattr(
        main,
        "batter_hits_training_examples_job_lock",
        Lock(),
    )
    monkeypatch.setattr(
        main,
        "run_batter_hits_training_example_build",
        fake_job,
    )
    monkeypatch.setattr(
        main,
        "_current_slate_date",
        lambda: date(2026, 6, 26),
    )
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/build-batter-hits-training-examples",
        headers={"Authorization": "Bearer cron-secret"},
        json={},
    )

    assert response.status_code == 200
    assert calls == [
        {
            "dry_run": False,
            "slate_date": None,
            "start_date": date(2026, 6, 25),
            "end_date": date(2026, 6, 26),
            "limit": 500,
        }
    ]
    assert response.json() == {
        "status": "completed",
        "resolved_window": {
            "slate_date": None,
            "start_date": "2026-06-25",
            "end_date": "2026-06-26",
            "limit": 500,
            "dry_run": False,
        },
        "candidates_found": 10,
        "candidates_deduped": 8,
        "examples_built": 7,
        "examples_upserted": 6,
        "skipped_missing_label": 1,
        "skipped_missing_history": 0,
        "skipped_unsupported_side": 2,
        "elapsed_seconds": 1.234,
    }


def test_build_batter_hits_training_examples_dry_run_passes_through(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_job(**kwargs: object) -> FeatureBuildSummary:
        calls.append(kwargs)
        return _feature_build_summary(examples_upserted=0)

    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setattr(
        main,
        "batter_hits_training_examples_job_lock",
        Lock(),
    )
    monkeypatch.setattr(
        main,
        "run_batter_hits_training_example_build",
        fake_job,
    )
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/build-batter-hits-training-examples",
        headers={"Authorization": "Bearer cron-secret"},
        json={
            "start_date": "2026-06-20",
            "end_date": "2026-06-22",
            "limit": 50,
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    assert calls == [
        {
            "dry_run": True,
            "slate_date": None,
            "start_date": date(2026, 6, 20),
            "end_date": date(2026, 6, 22),
            "limit": 50,
        }
    ]
    assert response.json()["examples_upserted"] == 0
    assert response.json()["resolved_window"] == {
        "slate_date": None,
        "start_date": "2026-06-20",
        "end_date": "2026-06-22",
        "limit": 50,
        "dry_run": True,
    }


def test_build_batter_hits_training_examples_allows_slate_date(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_job(**kwargs: object) -> FeatureBuildSummary:
        calls.append(kwargs)
        return _feature_build_summary()

    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setattr(
        main,
        "batter_hits_training_examples_job_lock",
        Lock(),
    )
    monkeypatch.setattr(
        main,
        "run_batter_hits_training_example_build",
        fake_job,
    )
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/build-batter-hits-training-examples",
        headers={"Authorization": "Bearer cron-secret"},
        json={
            "slate_date": "2026-06-24",
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    assert calls == [
        {
            "dry_run": True,
            "slate_date": date(2026, 6, 24),
            "start_date": None,
            "end_date": None,
            "limit": 500,
        }
    ]


def test_build_batter_hits_training_examples_rejects_mixed_dates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/build-batter-hits-training-examples",
        headers={"Authorization": "Bearer cron-secret"},
        json={
            "slate_date": "2026-06-24",
            "start_date": "2026-06-20",
            "end_date": "2026-06-22",
        },
    )

    assert response.status_code == 422


def test_build_batter_hits_training_examples_rejects_partial_range(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/build-batter-hits-training-examples",
        headers={"Authorization": "Bearer cron-secret"},
        json={"start_date": "2026-06-20"},
    )

    assert response.status_code == 422


def test_build_batter_hits_training_examples_rejects_invalid_range_order(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/build-batter-hits-training-examples",
        headers={"Authorization": "Bearer cron-secret"},
        json={
            "start_date": "2026-06-22",
            "end_date": "2026-06-20",
        },
    )

    assert response.status_code == 422


def test_build_batter_hits_training_examples_rejects_limit_above_cap(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs/build-batter-hits-training-examples",
        headers={"Authorization": "Bearer cron-secret"},
        json={"limit": 5001},
    )

    assert response.status_code == 422
