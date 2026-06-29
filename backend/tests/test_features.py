from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.domain import PlayerGameBatting
from app.features import (
    FEATURE_VERSION,
    build_training_example_for_prop,
    compute_rolling_batting_features,
    dedupe_training_prop_snapshots,
    run_batter_hits_training_example_build,
    target_over,
)
from tests.fixtures import candidate


def _batting(
    *,
    game_date: date,
    hits: int | None,
    event_id: str = "evt-1",
    player_name: str = "Player 1",
    at_bats: int | None = 4,
    plate_appearances: int | None = 4,
    walks: int | None = 0,
    strikeouts: int | None = 1,
    total_bases: int | None = 1,
) -> PlayerGameBatting:
    return PlayerGameBatting(
        provider="propline",
        provider_event_id=event_id,
        sport_key="baseball_mlb",
        game_date=game_date,
        commence_time=datetime(
            game_date.year,
            game_date.month,
            game_date.day,
            23,
            0,
            tzinfo=UTC,
        ),
        home_team="New York Yankees",
        away_team="Boston Red Sox",
        player_name=player_name,
        normalized_player_name="player1",
        team="New York Yankees",
        opponent="Boston Red Sox",
        is_home=True,
        hits=hits,
        at_bats=at_bats,
        plate_appearances=plate_appearances,
        walks=walks,
        strikeouts=strikeouts,
        total_bases=total_bases,
        rbis=None,
        runs=None,
        home_runs=None,
        raw_payload={"fixture": True},
    )


@pytest.mark.parametrize(
    ("actual_hits", "line", "expected"),
    [
        (1, 0.5, True),
        (0, 0.5, False),
        (2, 1.5, True),
        (1, 1.5, False),
    ],
)
def test_target_over(actual_hits: int, line: float, expected: bool) -> None:
    assert target_over(actual_hits, line, "over") is expected


def test_target_over_rejects_unsupported_side() -> None:
    with pytest.raises(ValueError):
        target_over(1, 0.5, "under")


def test_compute_rolling_batting_features_known_prior_games() -> None:
    prior_games = [
        _batting(game_date=date(2026, 6, 1), hits=1, total_bases=1),
        _batting(game_date=date(2026, 6, 2), hits=0, total_bases=0),
        _batting(game_date=date(2026, 6, 3), hits=2, total_bases=3),
    ]

    features = compute_rolling_batting_features(prior_games)

    assert features.prior_games_3 == 3
    assert features.hits_last_3 == 3
    assert features.hit_rate_last_3 == pytest.approx(2 / 3)
    assert features.avg_hits_last_10 == pytest.approx(1.0)
    assert features.avg_at_bats_last_10 == pytest.approx(4.0)
    assert features.avg_total_bases_last_10 == pytest.approx(4 / 3)
    assert features.strikeout_rate_last_10 == pytest.approx(3 / 12)
    assert features.walk_rate_last_10 == 0
    assert features.season_games_before == 3
    assert features.season_hits_before == 3
    assert features.season_hit_rate_before == pytest.approx(2 / 3)
    assert features.has_prior_batting_history is True
    assert features.is_cold_start is False


def test_training_example_filters_same_day_and_future_games() -> None:
    prop = candidate(
        index=1,
        line=0.5,
        commence_time=datetime(2026, 6, 3, 23, 0, tzinfo=UTC),
        snapshot_id=101,
    )
    label = _batting(game_date=date(2026, 6, 3), hits=0)
    prior_games = [
        _batting(game_date=date(2026, 6, 1), hits=1),
        _batting(game_date=date(2026, 6, 2), hits=2),
        _batting(game_date=date(2026, 6, 3), hits=3),
        _batting(game_date=date(2026, 6, 4), hits=4),
    ]

    example = build_training_example_for_prop(
        prop,
        label_row=label,
        prior_games=prior_games,
    )

    assert example is not None
    assert example.actual_hits == 0
    assert example.target_over is False
    assert example.features.prior_games_3 == 2
    assert example.features.hits_last_3 == 3


def test_training_example_season_features_ignore_prior_season_games() -> None:
    prop = candidate(
        index=1,
        line=0.5,
        commence_time=datetime(2026, 4, 3, 23, 0, tzinfo=UTC),
        snapshot_id=101,
    )
    label = _batting(game_date=date(2026, 4, 3), hits=1)
    prior_games = [
        _batting(game_date=date(2025, 9, 28), hits=2),
        _batting(game_date=date(2025, 9, 29), hits=1),
        _batting(game_date=date(2026, 3, 31), hits=0),
        _batting(game_date=date(2026, 4, 1), hits=1),
    ]

    example = build_training_example_for_prop(
        prop,
        label_row=label,
        prior_games=prior_games,
    )

    assert example is not None
    assert example.features.prior_games_3 == 3
    assert example.features.hits_last_3 == 2
    assert example.features.season_games_before == 2
    assert example.features.season_hits_before == 1
    assert example.features.season_hit_rate_before == pytest.approx(1 / 2)
    assert example.features.season_avg_hits_before == pytest.approx(1 / 2)


def test_missing_label_skips_example() -> None:
    prop = candidate(index=1, snapshot_id=101)
    label = _batting(game_date=date(2026, 6, 16), hits=None)

    assert (
        build_training_example_for_prop(
            prop,
            label_row=label,
            prior_games=[],
        )
        is None
    )


def test_missing_optional_batting_stats_do_not_become_fake_zeros() -> None:
    features = compute_rolling_batting_features(
        [
            _batting(
                game_date=date(2026, 6, 1),
                hits=1,
                at_bats=None,
                plate_appearances=None,
                walks=None,
                strikeouts=None,
                total_bases=None,
            )
        ]
    )

    assert features.hits_last_10 == 1
    assert features.avg_at_bats_last_10 is None
    assert features.avg_plate_appearances_last_10 is None
    assert features.avg_total_bases_last_10 is None
    assert features.strikeout_rate_last_10 is None
    assert features.walk_rate_last_10 is None


def test_cold_start_labeled_example_is_persisted_with_null_rates() -> None:
    prop = candidate(index=1, snapshot_id=101)
    label = _batting(game_date=date(2026, 6, 16), hits=1)

    example = build_training_example_for_prop(
        prop,
        label_row=label,
        prior_games=[],
    )

    assert example is not None
    assert example.feature_version == FEATURE_VERSION
    assert example.features.prior_games_3 == 0
    assert example.features.hits_last_10 == 0
    assert example.features.season_games_before == 0
    assert example.features.season_hits_before == 0
    assert example.features.hit_rate_last_10 is None
    assert example.features.season_avg_hits_before is None
    assert example.features.has_prior_batting_history is False
    assert example.features.is_cold_start is True
    assert example.metadata["cold_start_reason"] == "no_prior_batting_games"


def test_deduplication_chooses_latest_pre_game_snapshot() -> None:
    commence_time = datetime(2026, 6, 16, 23, 0, tzinfo=UTC)
    old_snapshot = candidate(
        index=1,
        commence_time=commence_time,
        snapshot_id=101,
    )
    latest_snapshot = type(old_snapshot)(
        **{
            **old_snapshot.__dict__,
            "id": 102,
            "captured_at": datetime(2026, 6, 16, 22, 0, tzinfo=UTC),
        }
    )
    post_start_snapshot = type(old_snapshot)(
        **{
            **old_snapshot.__dict__,
            "id": 103,
            "captured_at": datetime(2026, 6, 16, 23, 1, tzinfo=UTC),
        }
    )

    deduped = dedupe_training_prop_snapshots(
        [old_snapshot, latest_snapshot, post_start_snapshot]
    )

    assert len(deduped) == 1
    assert deduped[0].id == 102


def test_dry_run_does_not_write_training_examples(monkeypatch) -> None:
    writes: list[object] = []
    prop = candidate(index=1, snapshot_id=101)
    label = _batting(game_date=date(2026, 6, 16), hits=1)

    monkeypatch.setattr(
        "app.features.get_candidate_prop_snapshots_for_training",
        lambda *_args, **_kwargs: [prop],
    )
    monkeypatch.setattr(
        "app.features.get_player_game_batting_for_event",
        lambda *_args, **_kwargs: label,
    )
    monkeypatch.setattr(
        "app.features.get_prior_player_game_batting",
        lambda *_args, **_kwargs: [],
    )

    def fake_upsert(*_args, **kwargs) -> int:
        writes.append(kwargs["rows"])
        return 1

    monkeypatch.setattr(
        "app.features.upsert_batter_hits_training_examples",
        fake_upsert,
    )

    summary = run_batter_hits_training_example_build(
        dry_run=True,
        supabase=object(),  # type: ignore[arg-type]
    )

    assert summary.candidates_found == 1
    assert summary.candidates_deduped == 1
    assert summary.examples_built == 1
    assert summary.examples_upserted == 0
    assert writes == []
