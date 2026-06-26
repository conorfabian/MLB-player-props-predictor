from __future__ import annotations

from datetime import UTC, date, datetime
from collections.abc import Callable
from typing import Any, cast

import pytest

from app.domain import BoardPickForGrading
from app.grading import (
    find_player_hits,
    grade_prop_result,
    normalize_player_name,
    run_board_grading,
)
from app.propline_client import PropLineClient
from app.propline_models import PropLineEventStats
from app.settings import Settings
from tests.fixtures import candidate


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


def _pick(*, line: float = 0.5, player_name: str = "Jose Ramirez") -> BoardPickForGrading:
    snapshot = candidate(index=1, line=line, snapshot_id=101)
    snapshot = type(snapshot)(
        **{
            **snapshot.__dict__,
            "player_name": player_name,
            "provider_event_id": "evt-1",
        }
    )
    return BoardPickForGrading(
        id=11,
        board_id=1,
        slate_date=date(2026, 6, 16),
        rank=1,
        player_name=player_name,
        prop_type="hits",
        line=line,
        side="over",
        game_time=datetime(2026, 6, 16, 23, 0, tzinfo=UTC),
        result_status="pending",
        prop_snapshot_id=101,
        grading_metadata={},
        snapshot=snapshot,
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


@pytest.mark.parametrize(
    ("actual", "line", "side", "expected"),
    [
        (1, 0.5, "over", "hit"),
        (1, 1.5, "over", "miss"),
        (1, 1.0, "over", "push"),
        (0, 0.5, "under", "hit"),
        (1, 0.5, "under", "miss"),
    ],
)
def test_grade_prop_result(
    actual: float,
    line: float,
    side: str,
    expected: str,
) -> None:
    assert grade_prop_result(actual, line, side) == expected


def test_normalize_player_name() -> None:
    assert normalize_player_name(" José  Ramírez Jr. ") == "joseramirezjr"


def test_find_player_hits_reads_nested_stats() -> None:
    stats = PropLineEventStats.model_validate(
        {
            "id": "evt-1",
            "completed": True,
            "players": [
                {
                    "name": "Jose Ramirez",
                    "stats": {"hits": 2},
                }
            ],
        }
    )

    assert find_player_hits(stats, "José Ramírez") == 2


def test_find_player_hits_reads_flat_stat_rows() -> None:
    stats = PropLineEventStats.model_validate(
        {
            "id": "evt-1",
            "status": "final",
            "stats": [
                {
                    "player_name": "Jose Ramirez",
                    "stat_type": "at_bats",
                    "stat_value": 4,
                },
                {
                    "player_name": "Jose Ramirez",
                    "stat_type": "hits",
                    "stat_value": 2,
                },
            ],
        }
    )

    assert find_player_hits(stats, "José Ramírez") == 2


def test_missing_player_stats_remains_pending_without_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updates: list[dict[str, Any]] = []
    stats = PropLineEventStats.model_validate(
        {"id": "evt-1", "completed": True, "players": []}
    )

    monkeypatch.setattr(
        "app.grading.get_pending_board_picks_for_grading",
        lambda *_args, **_kwargs: [_pick()],
    )
    monkeypatch.setattr(
        "app.grading.update_board_pick_grading_result",
        lambda *_args, **kwargs: updates.append(kwargs),
    )

    summary = run_board_grading(
        settings=_settings(),
        supabase=object(),  # type: ignore[arg-type]
        client_factory=_client_factory(stats),
    )

    assert summary.graded == 0
    assert summary.still_pending == 1
    assert summary.skipped == 1
    assert updates[0]["result_status"] == "pending"
    assert updates[0]["actual_value"] is None
    assert updates[0]["grading_metadata"]["reason"] == "player_stats_missing"


def test_completed_game_updates_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updates: list[dict[str, Any]] = []
    stats = PropLineEventStats.model_validate(
        {
            "id": "evt-1",
            "completed": True,
            "players": [{"name": "Jose Ramirez", "stats": {"hits": 2}}],
        }
    )

    monkeypatch.setattr(
        "app.grading.get_pending_board_picks_for_grading",
        lambda *_args, **_kwargs: [_pick(line=1.5)],
    )
    monkeypatch.setattr(
        "app.grading.update_board_pick_grading_result",
        lambda *_args, **kwargs: updates.append(kwargs),
    )

    summary = run_board_grading(
        settings=_settings(),
        supabase=object(),  # type: ignore[arg-type]
        client_factory=_client_factory(stats),
    )

    assert summary.graded == 1
    assert summary.hits == 1
    assert updates[0]["result_status"] == "hit"
    assert updates[0]["actual_value"] == 2.0
    assert updates[0]["graded_at"] is not None


def test_dry_run_does_not_write_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updates: list[dict[str, Any]] = []
    stats = PropLineEventStats.model_validate(
        {
            "id": "evt-1",
            "completed": True,
            "players": [{"name": "Jose Ramirez", "stats": {"hits": 2}}],
        }
    )

    monkeypatch.setattr(
        "app.grading.get_pending_board_picks_for_grading",
        lambda *_args, **_kwargs: [_pick(line=1.5)],
    )
    monkeypatch.setattr(
        "app.grading.update_board_pick_grading_result",
        lambda *_args, **kwargs: updates.append(kwargs),
    )

    summary = run_board_grading(
        dry_run=True,
        settings=_settings(),
        supabase=object(),  # type: ignore[arg-type]
        client_factory=_client_factory(stats),
    )

    assert summary.graded == 1
    assert updates == []
