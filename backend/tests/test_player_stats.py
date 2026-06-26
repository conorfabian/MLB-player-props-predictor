from __future__ import annotations

from datetime import UTC, date, datetime

from app.domain import PlayerGameEventContext
from app.player_stats import (
    extract_int_stat,
    normalize_player_name,
    parse_player_game_batting,
)
from app.propline_models import PropLineEventStats


def _event_context() -> PlayerGameEventContext:
    return PlayerGameEventContext(
        provider="propline",
        provider_event_id="evt-1",
        sport_key="baseball_mlb",
        game_date=date(2026, 6, 16),
        commence_time=datetime(2026, 6, 16, 23, 0, tzinfo=UTC),
        home_team="New York Yankees",
        away_team="Boston Red Sox",
    )


def test_normalize_player_name() -> None:
    assert normalize_player_name(" José  Ramírez Jr. ") == "joseramirezjr"


def test_extract_int_stat_supports_aliases_and_zero() -> None:
    assert extract_int_stat({"H": "0"}, ["hits", "h"]) == 0
    assert extract_int_stat({"total-bases": 3}, ["total_bases"]) == 3


def test_parse_nested_batting_stats() -> None:
    stats = PropLineEventStats.model_validate(
        {
            "id": "evt-1",
            "completed": True,
            "players": [
                {
                    "name": "Jose Ramirez",
                    "team": "New York Yankees",
                    "stats": {
                        "hits": 2,
                        "at_bats": 4,
                        "total_bases": 5,
                    },
                }
            ],
        }
    )

    rows = parse_player_game_batting(stats, _event_context())

    assert len(rows) == 1
    assert rows[0].player_name == "Jose Ramirez"
    assert rows[0].normalized_player_name == "joseramirez"
    assert rows[0].team == "New York Yankees"
    assert rows[0].opponent == "Boston Red Sox"
    assert rows[0].is_home is True
    assert rows[0].hits == 2
    assert rows[0].at_bats == 4
    assert rows[0].total_bases == 5


def test_parse_flat_stat_rows() -> None:
    stats = PropLineEventStats.model_validate(
        {
            "id": "evt-1",
            "status": "final",
            "stats": [
                {
                    "player_name": "Jose Ramirez",
                    "team": "Boston Red Sox",
                    "stat_type": "at_bats",
                    "stat_value": 4,
                },
                {
                    "player_name": "Jose Ramirez",
                    "team": "Boston Red Sox",
                    "stat_type": "hits",
                    "stat_value": 2,
                },
            ],
        }
    )

    rows = parse_player_game_batting(stats, _event_context())

    assert len(rows) == 1
    assert rows[0].hits == 2
    assert rows[0].at_bats == 4
    assert rows[0].is_home is False
    assert rows[0].opponent == "New York Yankees"


def test_missing_hits_stays_none_when_other_batting_context_exists() -> None:
    stats = PropLineEventStats.model_validate(
        {
            "id": "evt-1",
            "completed": True,
            "players": [
                {
                    "name": "Jose Ramirez",
                    "stats": {"at_bats": 3},
                }
            ],
        }
    )

    rows = parse_player_game_batting(stats, _event_context())

    assert len(rows) == 1
    assert rows[0].hits is None
    assert rows[0].at_bats == 3


def test_skip_player_without_batting_context() -> None:
    stats = PropLineEventStats.model_validate(
        {
            "id": "evt-1",
            "completed": True,
            "players": [{"name": "Jose Ramirez", "stats": {"errors": 1}}],
        }
    )

    assert parse_player_game_batting(stats, _event_context()) == []
