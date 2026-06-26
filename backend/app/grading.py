from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from time import perf_counter
from typing import Any

from pydantic import ValidationError
from supabase import Client

from app.db import get_supabase
from app.domain import BoardPickForGrading
from app.player_stats import (
    extra_value,
    is_event_final,
    iter_stats_players,
    normalize_player_name,
    numeric_int,
    player_hits_from_stats,
    player_name_from_stats,
    stat_value,
)
from app.propline_client import PropLineClient, PropLineClientError
from app.propline_models import PropLineEventStats, PropLineStatsPlayer
from app.repositories import (
    get_pending_board_picks_for_grading,
    update_board_pick_grading_result,
)
from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GradingSummary:
    graded: int
    still_pending: int
    hits: int
    misses: int
    pushes: int
    skipped: int
    elapsed_seconds: float


@dataclass(frozen=True)
class PickGradingOutcome:
    pick_id: int
    result_status: str
    actual_value: float | None
    graded_at: datetime | None
    grading_metadata: dict[str, Any]
    skipped: bool = False


def run_board_grading(
    *,
    dry_run: bool = False,
    slate_date: date | None = None,
    settings: Settings | None = None,
    supabase: Client | None = None,
    client_factory: Callable[[Settings], PropLineClient] = PropLineClient,
) -> GradingSummary:
    settings = settings or get_settings()
    supabase = supabase or get_supabase()
    now = datetime.now(UTC)
    started = perf_counter()

    picks = get_pending_board_picks_for_grading(
        supabase,
        now=now,
        slate_date=slate_date,
    )
    stats_cache: dict[tuple[str, str], PropLineEventStats] = {}

    graded = 0
    still_pending = 0
    hits = 0
    misses = 0
    pushes = 0
    skipped = 0

    with client_factory(settings) as client:
        for pick in picks:
            outcome = _grade_pick(
                pick,
                client=client,
                stats_cache=stats_cache,
                now=now,
            )
            if not dry_run:
                update_board_pick_grading_result(
                    supabase,
                    pick_id=outcome.pick_id,
                    result_status=outcome.result_status,
                    actual_value=outcome.actual_value,
                    graded_at=outcome.graded_at,
                    grading_metadata=outcome.grading_metadata,
                )

            if outcome.result_status == "pending":
                still_pending += 1
            else:
                graded += 1
                if outcome.result_status == "hit":
                    hits += 1
                elif outcome.result_status == "miss":
                    misses += 1
                elif outcome.result_status == "push":
                    pushes += 1

            if outcome.skipped:
                skipped += 1

    elapsed = perf_counter() - started
    logger.info(
        "Board grading finished",
        extra={
            "graded": graded,
            "still_pending": still_pending,
            "hits": hits,
            "misses": misses,
            "pushes": pushes,
            "skipped": skipped,
            "elapsed_seconds": round(elapsed, 3),
        },
    )
    return GradingSummary(
        graded=graded,
        still_pending=still_pending,
        hits=hits,
        misses=misses,
        pushes=pushes,
        skipped=skipped,
        elapsed_seconds=elapsed,
    )


def grade_prop_result(actual_value: float, line: float, side: str) -> str:
    side_key = side.strip().lower()
    if actual_value == line:
        return "push"
    if side_key == "over":
        return "hit" if actual_value > line else "miss"
    if side_key == "under":
        return "hit" if actual_value < line else "miss"
    raise ValueError(f"Unsupported prop side: {side}")


def find_player_hits(
    stats_response: PropLineEventStats,
    player_name: str,
) -> int | None:
    return _find_player_hits_detail(stats_response, player_name)[0]


def _grade_pick(
    pick: BoardPickForGrading,
    *,
    client: PropLineClient,
    stats_cache: dict[tuple[str, str], PropLineEventStats],
    now: datetime,
) -> PickGradingOutcome:
    snapshot = pick.snapshot
    cache_key = (snapshot.sport_key, snapshot.provider_event_id)
    metadata = {
        **pick.grading_metadata,
        "provider": "propline",
        "stats_endpoint": (
            f"/sports/{snapshot.sport_key}/events/"
            f"{snapshot.provider_event_id}/stats"
        ),
        "graded_attempted_at": now.isoformat(),
    }

    try:
        stats = stats_cache.get(cache_key)
        if stats is None:
            stats = client.get_event_stats(*cache_key)
            stats_cache[cache_key] = stats
    except PropLineClientError as exc:
        return _pending(
            pick,
            metadata,
            reason="stats_fetch_failed",
            skipped=True,
            details={"status_code": exc.status_code},
        )

    if not is_event_final(stats):
        return _pending(pick, metadata, reason="event_not_final")

    actual_hits, reason = _find_player_hits_detail(
        stats,
        snapshot.player_name or pick.player_name,
    )
    if actual_hits is None:
        return _pending(pick, metadata, reason=reason, skipped=True)

    result_status = grade_prop_result(
        actual_value=float(actual_hits),
        line=pick.line,
        side=pick.side,
    )
    return PickGradingOutcome(
        pick_id=pick.id,
        result_status=result_status,
        actual_value=float(actual_hits),
        graded_at=now,
        grading_metadata={
            **metadata,
            "reason": "graded",
            "matched_player_name": snapshot.player_name,
            "actual_hits": actual_hits,
        },
    )


def _pending(
    pick: BoardPickForGrading,
    metadata: dict[str, Any],
    *,
    reason: str,
    skipped: bool = False,
    details: dict[str, Any] | None = None,
) -> PickGradingOutcome:
    return PickGradingOutcome(
        pick_id=pick.id,
        result_status="pending",
        actual_value=None,
        graded_at=None,
        grading_metadata={
            **metadata,
            "reason": reason,
            **(details or {}),
        },
        skipped=skipped,
    )


def _find_player_hits_detail(
    stats_response: PropLineEventStats,
    player_name: str,
) -> tuple[int | None, str]:
    target = normalize_player_name(player_name)
    matches = [
        player
        for player in _iter_players(stats_response)
        if normalize_player_name(_player_name(player)) == target
    ]
    if not matches:
        return None, "player_stats_missing"

    hit_values = [
        hits
        for player in matches
        if (hits := _player_hits(player)) is not None
    ]
    if not hit_values:
        return None, "player_hits_missing"
    if len(set(hit_values)) > 1:
        return None, "player_match_ambiguous"
    return hit_values[0], "found"


def _iter_players(
    stats_response: PropLineEventStats,
) -> Iterable[PropLineStatsPlayer]:
    yield from iter_stats_players(stats_response)


def _validate_players(values: list[Any]) -> Iterable[PropLineStatsPlayer]:
    for value in values:
        try:
            yield PropLineStatsPlayer.model_validate(value)
        except ValidationError:
            continue


def _player_name(player: PropLineStatsPlayer) -> str:
    return player_name_from_stats(player)


def _player_hits(player: PropLineStatsPlayer) -> int | None:
    return player_hits_from_stats(player)


def _event_status(stats_response: PropLineEventStats) -> str:
    for value in (
        stats_response.status,
        extra_value(stats_response, "event_status"),
        extra_value(stats_response, "game_status"),
        extra_value(stats_response, "status_detail"),
    ):
        if isinstance(value, str):
            return value.strip().lower()
    return ""


def _stat_value(stats: dict[str, Any] | None, key: str) -> Any:
    return stat_value(stats, key)


def _numeric_int(value: Any) -> int | None:
    return numeric_int(value)


def _extra(model: Any, key: str) -> Any:
    return extra_value(model, key)
