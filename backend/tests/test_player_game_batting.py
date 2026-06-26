from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import cast

from app.domain import PlayerGameBatting, PlayerGameEventContext
from app.player_game_batting import run_player_game_batting_backfill
from app.propline_client import PropLineClient
from app.propline_models import PropLineEventStats
from app.settings import Settings


def _settings() -> Settings:
    return Settings(
        supabase_url="https://example.supabase.co",
        supabase_secret_key="secret",
        frontend_origins=("http://localhost:3000",),
        propline_api_key="api-secret",
        propline_base_url="https://api.prop-line.com/v1",
        propline_timeout_seconds=30,
        slate_timezone="America/New_York",
        cron_job_secret="cron-secret",
    )


def _event(event_id: str = "evt-1") -> PlayerGameEventContext:
    return PlayerGameEventContext(
        provider="propline",
        provider_event_id=event_id,
        sport_key="baseball_mlb",
        game_date=date(2026, 6, 16),
        commence_time=datetime(2026, 6, 16, 23, 0, tzinfo=UTC),
        home_team="New York Yankees",
        away_team="Boston Red Sox",
    )


class FakeClient:
    def __init__(self, stats: PropLineEventStats) -> None:
        self.stats = stats
        self.calls: list[tuple[str, str]] = []

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get_event_stats(
        self,
        sport_key: str,
        event_id: str,
    ) -> PropLineEventStats:
        self.calls.append((sport_key, event_id))
        return self.stats


def _client_factory(
    stats: PropLineEventStats,
) -> Callable[[Settings], PropLineClient]:
    return cast(
        Callable[[Settings], PropLineClient],
        lambda _settings: FakeClient(stats),
    )


def test_dry_run_does_not_write_player_game_batting_rows(monkeypatch) -> None:
    writes: list[list[PlayerGameBatting]] = []
    stats = PropLineEventStats.model_validate(
        {
            "id": "evt-1",
            "completed": True,
            "players": [{"name": "Jose Ramirez", "stats": {"hits": 2}}],
        }
    )

    def fake_upsert(*_args, **kwargs) -> int:
        writes.append(kwargs["rows"])
        return 1

    monkeypatch.setattr(
        "app.player_game_batting.get_events_for_player_stats_backfill",
        lambda *_args, **_kwargs: [_event()],
    )
    monkeypatch.setattr(
        "app.player_game_batting.upsert_player_game_batting_rows",
        fake_upsert,
    )

    summary = run_player_game_batting_backfill(
        dry_run=True,
        settings=_settings(),
        supabase=object(),  # type: ignore[arg-type]
        client_factory=_client_factory(stats),
    )

    assert summary.events_found == 1
    assert summary.events_processed == 1
    assert summary.player_rows_parsed == 1
    assert summary.player_rows_upserted == 0
    assert writes == []


def test_non_dry_run_upserts_player_game_batting_rows(monkeypatch) -> None:
    writes: list[list[PlayerGameBatting]] = []
    stats = PropLineEventStats.model_validate(
        {
            "id": "evt-1",
            "status": "final",
            "players": [{"name": "Jose Ramirez", "stats": {"hits": 2}}],
        }
    )

    def fake_upsert(*_args, **kwargs) -> int:
        writes.append(kwargs["rows"])
        return 1

    monkeypatch.setattr(
        "app.player_game_batting.get_events_for_player_stats_backfill",
        lambda *_args, **_kwargs: [_event()],
    )
    monkeypatch.setattr(
        "app.player_game_batting.upsert_player_game_batting_rows",
        fake_upsert,
    )

    summary = run_player_game_batting_backfill(
        settings=_settings(),
        supabase=object(),  # type: ignore[arg-type]
        client_factory=_client_factory(stats),
    )

    assert summary.player_rows_upserted == 1
    assert writes[0][0].normalized_player_name == "joseramirez"


def test_non_final_event_is_skipped(monkeypatch) -> None:
    stats = PropLineEventStats.model_validate(
        {
            "id": "evt-1",
            "completed": False,
            "players": [{"name": "Jose Ramirez", "stats": {"hits": 2}}],
        }
    )

    monkeypatch.setattr(
        "app.player_game_batting.get_events_for_player_stats_backfill",
        lambda *_args, **_kwargs: [_event()],
    )
    monkeypatch.setattr(
        "app.player_game_batting.upsert_player_game_batting_rows",
        lambda *_args, **_kwargs: 1,
    )

    summary = run_player_game_batting_backfill(
        settings=_settings(),
        supabase=object(),  # type: ignore[arg-type]
        client_factory=_client_factory(stats),
    )

    assert summary.events_processed == 0
    assert summary.skipped_events == 1
    assert summary.player_rows_upserted == 0
