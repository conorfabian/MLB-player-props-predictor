from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from time import perf_counter

from supabase import Client

from app.db import get_supabase
from app.domain import PlayerGameEventContext
from app.player_stats import (
    count_player_stat_candidates,
    is_event_final,
    parse_player_game_batting,
)
from app.propline_client import PropLineClient, PropLineClientError
from app.repositories import (
    get_events_for_player_stats_backfill,
    upsert_player_game_batting_rows,
)
from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlayerGameBattingBackfillSummary:
    events_found: int
    events_processed: int
    player_rows_parsed: int
    player_rows_upserted: int
    skipped_events: int
    skipped_players: int
    elapsed_seconds: float


def run_player_game_batting_backfill(
    *,
    dry_run: bool = False,
    slate_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit_events: int | None = None,
    settings: Settings | None = None,
    supabase: Client | None = None,
    client_factory: Callable[[Settings], PropLineClient] = PropLineClient,
) -> PlayerGameBattingBackfillSummary:
    if slate_date is not None and (start_date is not None or end_date is not None):
        raise ValueError("--slate-date cannot be combined with date range flags.")
    if (start_date is None) != (end_date is None):
        raise ValueError("--start-date and --end-date must be provided together.")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("--start-date must be before or equal to --end-date.")
    if limit_events is not None and limit_events <= 0:
        raise ValueError("--limit-events must be positive.")

    settings = settings or get_settings()
    supabase = supabase or get_supabase()
    now = datetime.now(UTC)
    started = perf_counter()
    start_commence, end_commence = _date_window(
        slate_date=slate_date,
        start_date=start_date,
        end_date=end_date,
        settings=settings,
    )

    events = get_events_for_player_stats_backfill(
        supabase,
        now=now,
        start_commence_time=start_commence,
        end_commence_time=end_commence,
        limit_events=limit_events,
    )
    rows_to_upsert = []
    events_processed = 0
    skipped_events = 0
    skipped_players = 0

    with client_factory(settings) as client:
        for event in events:
            event_context = _with_local_game_date(event, settings)
            try:
                stats = client.get_event_stats(
                    event_context.sport_key,
                    event_context.provider_event_id,
                )
            except PropLineClientError:
                logger.exception(
                    "Failed to fetch player-game batting stats",
                    extra={
                        "provider_event_id": (
                            event_context.provider_event_id
                        )
                    },
                )
                skipped_events += 1
                continue

            if not is_event_final(stats):
                skipped_events += 1
                continue

            events_processed += 1
            candidate_count = count_player_stat_candidates(stats)
            parsed = parse_player_game_batting(stats, event_context)
            skipped_players += max(candidate_count - len(parsed), 0)
            rows_to_upsert.extend(parsed)

    player_rows_upserted = 0
    if rows_to_upsert and not dry_run:
        player_rows_upserted = upsert_player_game_batting_rows(
            supabase,
            rows=rows_to_upsert,
        )

    elapsed = perf_counter() - started
    logger.info(
        "Player-game batting backfill finished",
        extra={
            "events_found": len(events),
            "events_processed": events_processed,
            "player_rows_parsed": len(rows_to_upsert),
            "player_rows_upserted": player_rows_upserted,
            "skipped_events": skipped_events,
            "skipped_players": skipped_players,
            "elapsed_seconds": round(elapsed, 3),
        },
    )
    return PlayerGameBattingBackfillSummary(
        events_found=len(events),
        events_processed=events_processed,
        player_rows_parsed=len(rows_to_upsert),
        player_rows_upserted=player_rows_upserted,
        skipped_events=skipped_events,
        skipped_players=skipped_players,
        elapsed_seconds=elapsed,
    )


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


def _with_local_game_date(
    event: PlayerGameEventContext,
    settings: Settings,
) -> PlayerGameEventContext:
    return PlayerGameEventContext(
        provider=event.provider,
        provider_event_id=event.provider_event_id,
        sport_key=event.sport_key,
        game_date=event.commence_time.astimezone(
            settings.slate_zoneinfo
        ).date(),
        commence_time=event.commence_time,
        home_team=event.home_team,
        away_team=event.away_team,
    )
