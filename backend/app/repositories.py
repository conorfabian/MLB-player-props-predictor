from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import uuid4

from supabase import Client

from app.domain import (
    BoardDraft,
    BoardPickForGrading,
    IngestionRun,
    ModelRun,
    PropCandidate,
    ScoredCandidate,
)


class RepositoryError(RuntimeError):
    pass


def create_ingestion_run(
    supabase: Client,
    *,
    provider: str,
    sport_key: str,
    market_key: str,
    bookmaker_key: str,
    metadata: dict[str, Any] | None = None,
) -> IngestionRun:
    payload = {
        "id": str(uuid4()),
        "provider": provider,
        "sport_key": sport_key,
        "market_key": market_key,
        "bookmaker_key": bookmaker_key,
        "started_at": _iso(datetime.now(UTC)),
        "status": "running",
        "events_found": 0,
        "events_processed": 0,
        "offers_saved": 0,
        "metadata": metadata or {},
    }
    data = _single(
        cast(
            list[dict[str, Any]] | None,
            supabase.table("prop_ingestion_runs")
            .insert(cast(Any, payload))
            .execute()
            .data,
        )
    )
    return _ingestion_run(data)


def mark_ingestion_run_completed(
    supabase: Client,
    *,
    run_id: str,
    events_found: int,
    events_processed: int,
    offers_saved: int,
    metadata: dict[str, Any] | None = None,
) -> IngestionRun:
    payload: dict[str, Any] = {
        "completed_at": _iso(datetime.now(UTC)),
        "status": "completed",
        "events_found": events_found,
        "events_processed": events_processed,
        "offers_saved": offers_saved,
        "error_message": None,
    }
    if metadata is not None:
        payload["metadata"] = metadata
    data = _single(
        cast(
            list[dict[str, Any]] | None,
            supabase.table("prop_ingestion_runs")
        .update(payload)
        .eq("id", run_id)
        .execute()
            .data,
        )
    )
    return _ingestion_run(data)


def mark_ingestion_run_failed(
    supabase: Client,
    *,
    run_id: str,
    error_message: str,
    events_found: int = 0,
    events_processed: int = 0,
    offers_saved: int = 0,
    metadata: dict[str, Any] | None = None,
) -> IngestionRun:
    payload: dict[str, Any] = {
        "completed_at": _iso(datetime.now(UTC)),
        "status": "failed",
        "events_found": events_found,
        "events_processed": events_processed,
        "offers_saved": offers_saved,
        "error_message": _safe_error_message(error_message),
    }
    if metadata is not None:
        payload["metadata"] = metadata
    data = _single(
        cast(
            list[dict[str, Any]] | None,
            supabase.table("prop_ingestion_runs")
        .update(payload)
        .eq("id", run_id)
        .execute()
            .data,
        )
    )
    return _ingestion_run(data)


def insert_prop_snapshots(
    supabase: Client,
    *,
    ingestion_run_id: str,
    candidates: Sequence[PropCandidate],
    batch_size: int = 250,
) -> list[PropCandidate]:
    inserted: list[PropCandidate] = []
    rows = [
        _candidate_to_row(candidate, ingestion_run_id=ingestion_run_id)
        for candidate in candidates
    ]

    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        result = (
            supabase.table("prop_snapshots")
            .insert(cast(Any, batch))
            .execute()
        )
        result_rows = cast(list[dict[str, Any]], result.data or [])
        inserted.extend(_candidate_from_row(row) for row in result_rows)

    return inserted


def get_latest_completed_ingestion_run(
    supabase: Client,
) -> IngestionRun | None:
    runs = get_completed_ingestion_runs(supabase, limit=1)
    return runs[0] if runs else None


def get_completed_ingestion_runs(
    supabase: Client,
    *,
    limit: int | None = None,
) -> list[IngestionRun]:
    query = (
        supabase.table("prop_ingestion_runs")
        .select("*")
        .eq("status", "completed")
        .order("completed_at", desc=True)
    )
    if limit is not None:
        query = query.limit(limit)
    result = query.execute()
    rows = cast(list[dict[str, Any]], result.data or [])
    return [_ingestion_run(row) for row in rows]


def get_eligible_snapshots_for_run(
    supabase: Client,
    *,
    ingestion_run_id: str,
    now: datetime,
) -> list[PropCandidate]:
    result = (
        supabase.table("prop_snapshots")
        .select("*")
        .eq("ingestion_run_id", ingestion_run_id)
        .eq("provider", "propline")
        .eq("sport_key", "baseball_mlb")
        .eq("bookmaker_key", "prizepicks")
        .eq("market_key", "batter_hits")
        .eq("outcome_name", "over")
        .gt("commence_time", _iso(now.astimezone(UTC)))
        .order("commence_time")
        .execute()
    )
    rows = cast(list[dict[str, Any]], result.data or [])
    return [_candidate_from_row(row) for row in rows]


def get_pending_board_picks_for_grading(
    supabase: Client,
    *,
    now: datetime,
    slate_date: date | None = None,
) -> list[BoardPickForGrading]:
    query = (
        supabase.table("board_picks")
        .select(
            "id, board_id, rank, player_name, prop_type, line, side, "
            "game_time, result_status, prop_snapshot_id, grading_metadata, "
            "daily_boards!inner(slate_date), "
            "prop_snapshots!inner(*)"
        )
        .eq("result_status", "pending")
        .eq("prop_type", "hits")
        .eq("side", "over")
        .order("game_time")
    )
    if slate_date is not None:
        query = query.eq("daily_boards.slate_date", slate_date.isoformat())
    else:
        query = query.lte("game_time", _iso(now.astimezone(UTC)))

    rows = cast(list[dict[str, Any]], query.execute().data or [])
    return [_board_pick_for_grading(row) for row in rows]


def update_board_pick_grading_result(
    supabase: Client,
    *,
    pick_id: int,
    result_status: str,
    actual_value: float | None,
    graded_at: datetime | None,
    grading_metadata: dict[str, Any],
) -> None:
    payload: dict[str, Any] = {
        "result_status": result_status,
        "actual_value": actual_value,
        "graded_at": _optional_iso(graded_at),
        "grading_metadata": grading_metadata,
    }
    supabase.table("board_picks").update(payload).eq("id", pick_id).execute()


def create_model_run(
    supabase: Client,
    *,
    ingestion_run_id: str,
    run_type: str,
    model_version: str,
    feature_version: str,
    metadata: dict[str, Any] | None = None,
) -> ModelRun:
    payload = {
        "id": str(uuid4()),
        "ingestion_run_id": ingestion_run_id,
        "run_type": run_type,
        "model_version": model_version,
        "feature_version": feature_version,
        "started_at": _iso(datetime.now(UTC)),
        "status": "running",
        "candidate_count": 0,
        "published_count": 0,
        "metadata": metadata or {},
    }
    data = _single(
        cast(
            list[dict[str, Any]] | None,
            supabase.table("model_runs")
            .insert(cast(Any, payload))
            .execute()
            .data,
        )
    )
    return _model_run(data)


def mark_model_run_completed(
    supabase: Client,
    *,
    model_run_id: str,
    candidate_count: int,
    published_count: int,
    metadata: dict[str, Any] | None = None,
) -> ModelRun:
    payload: dict[str, Any] = {
        "completed_at": _iso(datetime.now(UTC)),
        "status": "completed",
        "candidate_count": candidate_count,
        "published_count": published_count,
        "error_message": None,
    }
    if metadata is not None:
        payload["metadata"] = metadata
    data = _single(
        cast(
            list[dict[str, Any]] | None,
            supabase.table("model_runs")
        .update(payload)
        .eq("id", model_run_id)
        .execute()
            .data,
        )
    )
    return _model_run(data)


def mark_model_run_failed(
    supabase: Client,
    *,
    model_run_id: str,
    error_message: str,
) -> ModelRun:
    data = _single(
        cast(
            list[dict[str, Any]] | None,
            supabase.table("model_runs")
        .update(
            {
                "completed_at": _iso(datetime.now(UTC)),
                "status": "failed",
                "error_message": _safe_error_message(error_message),
            }
        )
        .eq("id", model_run_id)
        .execute()
            .data,
        )
    )
    return _model_run(data)


def insert_candidate_predictions(
    supabase: Client,
    *,
    model_run_id: str,
    scored_candidates: Sequence[ScoredCandidate],
    batch_size: int = 250,
) -> None:
    rows = [
        {
            "model_run_id": model_run_id,
            "prop_snapshot_id": scored.candidate.id,
            "predicted_probability": scored.predicted_probability,
            "rank": scored.rank,
            "eligible": scored.eligible,
            "exclusion_reason": scored.exclusion_reason,
        }
        for scored in scored_candidates
    ]
    for start in range(0, len(rows), batch_size):
        supabase.table("candidate_predictions").insert(
            cast(Any, rows[start : start + batch_size])
        ).execute()


def publish_daily_board(
    supabase: Client,
    *,
    board: BoardDraft,
) -> None:
    payload = {
        "p_slate_date": board.slate_date.isoformat(),
        "p_model_version": board.model_version,
        "p_status": board.status,
        "p_metadata": board.metadata,
        "p_picks": [
            {
                "rank": pick.rank,
                "player_name": pick.player_name,
                "team": pick.team,
                "opponent": pick.opponent,
                "prop_type": pick.prop_type,
                "line": pick.line,
                "side": pick.side,
                "model_probability": pick.model_probability,
                "game_time": _iso(pick.game_time),
                "result_status": pick.result_status,
                "prop_snapshot_id": pick.prop_snapshot_id,
                "model_run_id": pick.model_run_id,
                "provider": pick.provider,
                "bookmaker_key": pick.bookmaker_key,
                "metadata": pick.metadata,
            }
            for pick in board.picks
        ],
    }
    supabase.rpc("publish_daily_board", payload).execute()


def _candidate_to_row(
    candidate: PropCandidate,
    *,
    ingestion_run_id: str,
) -> dict[str, Any]:
    return {
        "ingestion_run_id": ingestion_run_id,
        "provider": candidate.provider,
        "provider_event_id": candidate.provider_event_id,
        "sport_key": candidate.sport_key,
        "commence_time": _iso(candidate.commence_time),
        "home_team": candidate.home_team,
        "away_team": candidate.away_team,
        "bookmaker_key": candidate.bookmaker_key,
        "bookmaker_title": candidate.bookmaker_title,
        "market_key": candidate.market_key,
        "outcome_name": candidate.outcome_name,
        "player_name": candidate.player_name,
        "line": candidate.line,
        "price_american": candidate.price_american,
        "dfs_odds_type": candidate.dfs_odds_type,
        "market_last_update": _optional_iso(candidate.market_last_update),
        "source_recorded_at": _optional_iso(candidate.source_recorded_at),
        "source_book_updated_at": _optional_iso(
            candidate.source_book_updated_at
        ),
        "captured_at": _iso(candidate.captured_at),
        "raw_payload": candidate.raw_payload,
    }


def _candidate_from_row(row: dict[str, Any]) -> PropCandidate:
    return PropCandidate(
        id=row.get("id"),
        provider=row["provider"],
        provider_event_id=row["provider_event_id"],
        sport_key=row["sport_key"],
        commence_time=_parse_datetime(row["commence_time"]),
        home_team=row["home_team"],
        away_team=row["away_team"],
        bookmaker_key=row["bookmaker_key"],
        bookmaker_title=row.get("bookmaker_title"),
        market_key=row["market_key"],
        outcome_name=row["outcome_name"],
        player_name=row["player_name"],
        line=float(row["line"]),
        price_american=row.get("price_american"),
        dfs_odds_type=row.get("dfs_odds_type"),
        market_last_update=_parse_optional_datetime(
            row.get("market_last_update")
        ),
        source_recorded_at=_parse_optional_datetime(
            row.get("source_recorded_at")
        ),
        source_book_updated_at=_parse_optional_datetime(
            row.get("source_book_updated_at")
        ),
        captured_at=_parse_datetime(row["captured_at"]),
        raw_payload=row.get("raw_payload") or {},
    )


def _board_pick_for_grading(row: dict[str, Any]) -> BoardPickForGrading:
    board = row.get("daily_boards") or {}
    snapshot_row = row.get("prop_snapshots") or {}
    if not snapshot_row:
        raise RepositoryError("Pending board pick has no prop snapshot.")

    return BoardPickForGrading(
        id=int(row["id"]),
        board_id=int(row["board_id"]),
        slate_date=_parse_date(board["slate_date"]),
        rank=int(row["rank"]),
        player_name=row["player_name"],
        prop_type=row["prop_type"],
        line=float(row["line"]),
        side=row["side"],
        game_time=_parse_optional_datetime(row.get("game_time")),
        result_status=row["result_status"],
        prop_snapshot_id=int(row["prop_snapshot_id"]),
        grading_metadata=row.get("grading_metadata") or {},
        snapshot=_candidate_from_row(snapshot_row),
    )


def _ingestion_run(row: dict[str, Any]) -> IngestionRun:
    return IngestionRun(
        id=row["id"],
        provider=row["provider"],
        sport_key=row["sport_key"],
        market_key=row["market_key"],
        bookmaker_key=row["bookmaker_key"],
        started_at=_parse_datetime(row["started_at"]),
        completed_at=_parse_optional_datetime(row.get("completed_at")),
        status=row["status"],
        events_found=row.get("events_found") or 0,
        events_processed=row.get("events_processed") or 0,
        offers_saved=row.get("offers_saved") or 0,
        error_message=row.get("error_message"),
        metadata=row.get("metadata") or {},
    )


def _model_run(row: dict[str, Any]) -> ModelRun:
    return ModelRun(
        id=row["id"],
        ingestion_run_id=row["ingestion_run_id"],
        run_type=row["run_type"],
        model_version=row["model_version"],
        feature_version=row["feature_version"],
        status=row["status"],
    )


def _single(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not rows:
        raise RepositoryError("Database operation returned no rows.")
    return rows[0]


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _optional_iso(value: datetime | None) -> str | None:
    return _iso(value) if value else None


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_optional_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value)


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _safe_error_message(message: str) -> str:
    return message[:1000]
