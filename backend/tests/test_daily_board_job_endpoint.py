from __future__ import annotations

from datetime import date
from threading import Lock

from fastapi.testclient import TestClient

from app import main
from app.pipeline import (
    BoardGenerationSummary,
    DailyBoardJobSummary,
    IngestionSummary,
)
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
