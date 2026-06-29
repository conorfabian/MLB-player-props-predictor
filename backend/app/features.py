from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from time import perf_counter

from supabase import Client

from app.db import get_supabase
from app.domain import (
    BatterHitsFeatureRow,
    BatterHitsTrainingExample,
    FeatureBuildSummary,
    PlayerGameBatting,
    PropCandidate,
)
from app.player_stats import normalize_player_name
from app.repositories import (
    get_candidate_prop_snapshots_for_training,
    get_player_game_batting_for_event,
    get_prior_player_game_batting,
    upsert_batter_hits_training_examples,
)
from app.settings import Settings, get_api_settings

FEATURE_VERSION = "rolling-batter-hits-v2"

logger = logging.getLogger(__name__)


def run_batter_hits_training_example_build(
    *,
    dry_run: bool = False,
    slate_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int | None = None,
    settings: Settings | None = None,
    supabase: Client | None = None,
) -> FeatureBuildSummary:
    if slate_date is not None and (start_date is not None or end_date is not None):
        raise ValueError("--slate-date cannot be combined with date range flags.")
    if (start_date is None) != (end_date is None):
        raise ValueError("--start-date and --end-date must be provided together.")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("--start-date must be before or equal to --end-date.")
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be positive.")

    settings = settings or get_api_settings()
    supabase = supabase or get_supabase()
    now = datetime.now(UTC)
    started = perf_counter()
    start_commence, end_commence = _date_window(
        slate_date=slate_date,
        start_date=start_date,
        end_date=end_date,
        settings=settings,
    )

    candidates = get_candidate_prop_snapshots_for_training(
        supabase,
        now=now,
        start_commence_time=start_commence,
        end_commence_time=end_commence,
        limit=limit,
    )
    deduped = dedupe_training_prop_snapshots(candidates)
    examples: list[BatterHitsTrainingExample] = []
    skipped_missing_label = 0
    skipped_unsupported_side = 0

    for candidate in deduped:
        normalized_name = normalize_player_name(candidate.player_name)
        label = get_player_game_batting_for_event(
            supabase,
            provider=candidate.provider,
            provider_event_id=candidate.provider_event_id,
            normalized_player_name=normalized_name,
        )
        if label is None or label.hits is None:
            skipped_missing_label += 1
            continue

        prior_games = get_prior_player_game_batting(
            supabase,
            provider=candidate.provider,
            sport_key=candidate.sport_key,
            normalized_player_name=normalized_name,
            before_game_date=label.game_date,
        )
        example = build_training_example_for_prop(
            candidate,
            label_row=label,
            prior_games=prior_games,
        )
        if example is None:
            skipped_unsupported_side += 1
            continue
        examples.append(example)

    examples_upserted = 0
    if examples and not dry_run:
        examples_upserted = upsert_batter_hits_training_examples(
            supabase,
            rows=examples,
        )

    elapsed = perf_counter() - started
    summary = FeatureBuildSummary(
        candidates_found=len(candidates),
        candidates_deduped=len(deduped),
        examples_built=len(examples),
        examples_upserted=examples_upserted,
        skipped_missing_label=skipped_missing_label,
        skipped_missing_history=0,
        skipped_unsupported_side=skipped_unsupported_side,
        elapsed_seconds=elapsed,
    )
    logger.info(
        "Batter hits training example build finished",
        extra={
            "candidates_found": summary.candidates_found,
            "candidates_deduped": summary.candidates_deduped,
            "examples_built": summary.examples_built,
            "examples_upserted": summary.examples_upserted,
            "skipped_missing_label": summary.skipped_missing_label,
            "skipped_missing_history": summary.skipped_missing_history,
            "skipped_unsupported_side": summary.skipped_unsupported_side,
            "elapsed_seconds": round(summary.elapsed_seconds, 3),
        },
    )
    return summary


def dedupe_training_prop_snapshots(
    candidates: Sequence[PropCandidate],
) -> list[PropCandidate]:
    grouped: dict[tuple[str, str, str, str, str, str, float, str], PropCandidate] = {}
    for candidate in candidates:
        side = candidate.outcome_name.strip().lower()
        if candidate.captured_at > candidate.commence_time:
            continue
        key = (
            candidate.provider,
            candidate.provider_event_id,
            normalize_player_name(candidate.player_name),
            candidate.sport_key,
            candidate.market_key,
            candidate.bookmaker_key,
            candidate.line,
            side,
        )
        current = grouped.get(key)
        if current is None or candidate.captured_at > current.captured_at:
            grouped[key] = candidate
    return sorted(grouped.values(), key=lambda item: (item.commence_time, item.id or 0))


def build_training_example_for_prop(
    prop: PropCandidate,
    *,
    label_row: PlayerGameBatting,
    prior_games: Sequence[PlayerGameBatting],
) -> BatterHitsTrainingExample | None:
    side = prop.outcome_name.strip().lower()
    if side != "over":
        return None
    if prop.id is None or label_row.hits is None:
        return None

    pregame_history = [
        game for game in prior_games if game.game_date < label_row.game_date
    ]
    features = compute_rolling_batting_features(
        pregame_history,
        target_game_date=label_row.game_date,
    )
    metadata = {
        "source": "prop_snapshots_player_game_batting",
        "selected_snapshot_captured_at": prop.captured_at.isoformat(),
    }
    if features.is_cold_start:
        metadata["cold_start_reason"] = "no_prior_batting_games"

    return BatterHitsTrainingExample(
        prop_snapshot_id=prop.id,
        provider=prop.provider,
        provider_event_id=prop.provider_event_id,
        sport_key=prop.sport_key,
        bookmaker_key=prop.bookmaker_key,
        market_key=prop.market_key,
        player_name=prop.player_name,
        normalized_player_name=normalize_player_name(prop.player_name),
        game_date=label_row.game_date,
        commence_time=prop.commence_time,
        home_team=prop.home_team,
        away_team=prop.away_team,
        line=prop.line,
        side=side,
        actual_hits=label_row.hits,
        target_over=target_over(label_row.hits, prop.line, side),
        feature_version=FEATURE_VERSION,
        features=features,
        metadata=metadata,
    )


def compute_rolling_batting_features(
    prior_games: Sequence[PlayerGameBatting],
    *,
    target_game_date: date | None = None,
) -> BatterHitsFeatureRow:
    ordered = sorted(
        [game for game in prior_games if game.hits is not None],
        key=lambda game: (
            game.game_date,
            game.commence_time or datetime.min.replace(tzinfo=UTC),
        ),
        reverse=True,
    )
    last_3 = ordered[:3]
    last_5 = ordered[:5]
    last_10 = ordered[:10]
    season_games = _current_season_games(
        ordered,
        target_game_date=target_game_date,
    )
    season_games_before = len(season_games)
    season_hits_before = _sum_present(game.hits for game in season_games)
    has_history = season_games_before > 0

    return BatterHitsFeatureRow(
        prior_games_3=len(last_3),
        prior_games_5=len(last_5),
        prior_games_10=len(last_10),
        hits_last_3=_sum_present(game.hits for game in last_3),
        hits_last_5=_sum_present(game.hits for game in last_5),
        hits_last_10=_sum_present(game.hits for game in last_10),
        hit_rate_last_3=_hit_rate(last_3),
        hit_rate_last_5=_hit_rate(last_5),
        hit_rate_last_10=_hit_rate(last_10),
        avg_hits_last_10=_average_stat(last_10, "hits"),
        avg_at_bats_last_10=_average_stat(last_10, "at_bats"),
        avg_plate_appearances_last_10=_average_stat(
            last_10,
            "plate_appearances",
        ),
        avg_total_bases_last_10=_average_stat(last_10, "total_bases"),
        strikeout_rate_last_10=_rate(last_10, "strikeouts", "plate_appearances"),
        walk_rate_last_10=_rate(last_10, "walks", "plate_appearances"),
        season_games_before=season_games_before,
        season_hits_before=season_hits_before,
        season_hit_rate_before=_hit_rate(season_games),
        season_avg_hits_before=(
            season_hits_before / season_games_before if season_games_before else None
        ),
        has_prior_batting_history=has_history,
        is_cold_start=not has_history,
    )


def target_over(actual_hits: int, line: float, side: str) -> bool:
    side_key = side.strip().lower()
    if side_key != "over":
        raise ValueError(f"Unsupported prop side: {side}")
    return actual_hits > line


def _hit_rate(games: Sequence[PlayerGameBatting]) -> float | None:
    if not games:
        return None
    return sum(1 for game in games if (game.hits or 0) > 0) / len(games)


def _average_stat(
    games: Sequence[PlayerGameBatting],
    attr: str,
) -> float | None:
    values = [
        value
        for game in games
        if (value := getattr(game, attr)) is not None
    ]
    if not values:
        return None
    return sum(values) / len(values)


def _rate(
    games: Sequence[PlayerGameBatting],
    numerator_attr: str,
    denominator_attr: str,
) -> float | None:
    numerator = 0
    denominator = 0
    for game in games:
        num_value = getattr(game, numerator_attr)
        den_value = getattr(game, denominator_attr)
        if num_value is None or den_value is None:
            continue
        numerator += num_value
        denominator += den_value
    if denominator == 0:
        return None
    return numerator / denominator


def _sum_present(values: Iterable[int | None]) -> int:
    return sum(value for value in values if value is not None)


def _current_season_games(
    games: Sequence[PlayerGameBatting],
    *,
    target_game_date: date | None,
) -> list[PlayerGameBatting]:
    if target_game_date is None:
        return list(games)
    season_start = date(target_game_date.year, 1, 1)
    return [
        game
        for game in games
        if season_start <= game.game_date < target_game_date
    ]


def _date_window(
    *,
    slate_date: date | None,
    start_date: date | None,
    end_date: date | None,
    settings: Settings,
) -> tuple[datetime | None, datetime | None]:
    if slate_date is not None:
        start_date = slate_date
        end_date = slate_date
    if start_date is None or end_date is None:
        return None, None

    zone = settings.slate_zoneinfo
    start_local = datetime.combine(start_date, time.min, tzinfo=zone)
    end_local = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=zone,
    )
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
