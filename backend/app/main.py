import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from threading import Lock
from typing import Any, cast

from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db import get_supabase
from app.dataset_health import get_batter_hits_dataset_health
from app.domain import FeatureBuildSummary
from app.features import run_batter_hits_training_example_build
from app.grading import GradingSummary, run_board_grading
from app.pipeline import DailyBoardJobSummary, run_daily_board_job
from app.player_game_batting import (
    PlayerGameBattingBackfillSummary,
    run_player_game_batting_backfill,
)
from app.schemas import BoardResponse, PickResponse
from app.settings import get_api_settings

logger = logging.getLogger(__name__)

DEFAULT_PLAYER_GAME_BATTING_LIMIT_EVENTS = 50
MAX_PLAYER_GAME_BATTING_LIMIT_EVENTS = 100
DEFAULT_BATTER_HITS_TRAINING_EXAMPLE_LIMIT = 500
MAX_BATTER_HITS_TRAINING_EXAMPLE_LIMIT = 5000

app = FastAPI(
    title="MLB Props Predictor API",
    version="0.1.0",
)

settings = get_api_settings()
job_lock = Lock()
grading_job_lock = Lock()
player_game_batting_job_lock = Lock()
batter_hits_training_examples_job_lock = Lock()


class PlayerGameBattingBackfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slate_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    limit_events: int | None = Field(
        default=None,
        gt=0,
        le=MAX_PLAYER_GAME_BATTING_LIMIT_EVENTS,
    )
    dry_run: bool = False

    @model_validator(mode="after")
    def validate_date_window(self) -> "PlayerGameBattingBackfillRequest":
        has_range = self.start_date is not None or self.end_date is not None
        if self.slate_date is not None and has_range:
            raise ValueError(
                "slate_date cannot be combined with start_date or end_date."
            )
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError(
                "start_date and end_date must be provided together."
            )
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date must be before or equal to end_date.")
        return self


class BatterHitsTrainingExampleBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slate_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    limit: int | None = Field(
        default=None,
        gt=0,
        le=MAX_BATTER_HITS_TRAINING_EXAMPLE_LIMIT,
    )
    dry_run: bool = False

    @model_validator(mode="after")
    def validate_date_window(self) -> "BatterHitsTrainingExampleBuildRequest":
        has_range = self.start_date is not None or self.end_date is not None
        if self.slate_date is not None and has_range:
            raise ValueError(
                "slate_date cannot be combined with start_date or end_date."
            )
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError(
                "start_date and end_date must be provided together."
            )
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date must be before or equal to end_date.")
        return self


@dataclass(frozen=True)
class ResolvedPlayerGameBattingBackfillRequest:
    slate_date: date | None
    start_date: date | None
    end_date: date | None
    limit_events: int
    dry_run: bool


@dataclass(frozen=True)
class ResolvedBatterHitsTrainingExampleBuildRequest:
    slate_date: date | None
    start_date: date | None
    end_date: date | None
    limit: int
    dry_run: bool


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.frontend_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "mlb-props-api",
    }


@app.post("/api/jobs/daily-board")
def run_daily_board_endpoint(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_cron_auth(authorization)
    if not job_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Daily board job is already running.",
        )

    try:
        summary = run_daily_board_job()
        return _daily_board_summary(summary)
    except Exception as exc:
        logger.exception("Daily board cron job failed")
        raise HTTPException(
            status_code=500,
            detail="Daily board job failed.",
        ) from exc
    finally:
        job_lock.release()


@app.post("/api/jobs/grade-board")
def run_grade_board_endpoint(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_cron_auth(authorization)
    if not grading_job_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Board grading job is already running.",
        )

    try:
        summary = run_board_grading()
        return _grading_summary(summary)
    except Exception as exc:
        logger.exception("Board grading cron job failed")
        raise HTTPException(
            status_code=500,
            detail="Board grading job failed.",
        ) from exc
    finally:
        grading_job_lock.release()


@app.post("/api/jobs/backfill-player-game-batting")
def run_backfill_player_game_batting_endpoint(
    request: PlayerGameBattingBackfillRequest | None = Body(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_cron_auth(authorization)
    resolved_request = _resolve_player_game_batting_backfill_request(request)
    if not player_game_batting_job_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Player-game batting backfill job is already running.",
        )

    try:
        summary = run_player_game_batting_backfill(
            dry_run=resolved_request.dry_run,
            slate_date=resolved_request.slate_date,
            start_date=resolved_request.start_date,
            end_date=resolved_request.end_date,
            limit_events=resolved_request.limit_events,
        )
        return _player_game_batting_summary(summary, resolved_request)
    except Exception as exc:
        logger.exception("Player-game batting backfill cron job failed")
        raise HTTPException(
            status_code=500,
            detail="Player-game batting backfill job failed.",
        ) from exc
    finally:
        player_game_batting_job_lock.release()


@app.post("/api/jobs/build-batter-hits-training-examples")
def run_build_batter_hits_training_examples_endpoint(
    request: BatterHitsTrainingExampleBuildRequest | None = Body(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_cron_auth(authorization)
    resolved_request = _resolve_batter_hits_training_example_build_request(
        request,
    )
    if not batter_hits_training_examples_job_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Batter hits training example build is already running.",
        )

    try:
        summary = run_batter_hits_training_example_build(
            dry_run=resolved_request.dry_run,
            slate_date=resolved_request.slate_date,
            start_date=resolved_request.start_date,
            end_date=resolved_request.end_date,
            limit=resolved_request.limit,
        )
        return _batter_hits_training_example_build_summary(
            summary,
            resolved_request,
        )
    except Exception as exc:
        logger.exception("Batter hits training example cron job failed")
        raise HTTPException(
            status_code=500,
            detail="Batter hits training example build failed.",
        ) from exc
    finally:
        batter_hits_training_examples_job_lock.release()


@app.get(
    "/api/boards/latest",
    response_model=BoardResponse,
)
def get_latest_board() -> BoardResponse:
    supabase = get_supabase()

    board_result = (
        supabase.table("daily_boards")
        .select(
            "id, slate_date, generated_at, "
            "model_version, status"
        )
        .eq("status", "published")
        .order("slate_date", desc=True)
        .limit(1)
        .execute()
    )

    boards = cast(list[dict[str, Any]], board_result.data or [])

    if not boards:
        raise HTTPException(
            status_code=404,
            detail="No published board was found.",
        )

    board = boards[0]

    picks_result = (
        supabase.table("board_picks")
        .select(
            "rank, player_name, team, opponent, "
            "prop_type, line, side, model_probability, "
            "game_time, result_status, actual_value, graded_at"
        )
        .eq("board_id", board["id"])
        .order("rank")
        .execute()
    )

    picks = [
        PickResponse(**pick)
        for pick in cast(list[dict[str, Any]], picks_result.data or [])
    ]

    return BoardResponse(
        slate_date=board["slate_date"],
        generated_at=board["generated_at"],
        model_version=board["model_version"],
        status=board["status"],
        picks=picks,
    )


@app.get("/api/dataset-health/batter-hits")
def get_batter_hits_dataset_health_endpoint() -> dict[str, Any]:
    return get_batter_hits_dataset_health()


def _require_cron_auth(authorization: str | None) -> None:
    secret = settings.cron_job_secret
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Cron job secret is not configured.",
        )

    expected = f"Bearer {secret}"
    if authorization is None or not secrets.compare_digest(
        authorization,
        expected,
    ):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized.",
        )


def _daily_board_summary(summary: DailyBoardJobSummary) -> dict[str, Any]:
    return {
        "status": "completed",
        "ingestion": {
            "run_id": summary.ingestion.run_id,
            "events_found": summary.ingestion.events_found,
            "events_processed": summary.ingestion.events_processed,
            "offers_normalized": summary.ingestion.offers_normalized,
            "offers_saved": summary.ingestion.offers_saved,
            "skipped_non_prizepicks": (
                summary.ingestion.skipped_non_prizepicks
            ),
            "skipped_nonstandard_dfs": (
                summary.ingestion.skipped_nonstandard_dfs
            ),
            "skipped_malformed": summary.ingestion.skipped_malformed,
            "elapsed_seconds": round(summary.ingestion.elapsed_seconds, 3),
        },
        "board": {
            "slate_date": summary.board.slate_date.isoformat(),
            "ingestion_run_id": summary.board.ingestion_run_id,
            "candidates": summary.board.candidates,
            "published": summary.board.published,
            "model_version": summary.board.model_version,
            "elapsed_seconds": round(summary.board.elapsed_seconds, 3),
        },
    }


def _grading_summary(summary: GradingSummary) -> dict[str, Any]:
    return {
        "status": "completed",
        "graded": summary.graded,
        "still_pending": summary.still_pending,
        "hits": summary.hits,
        "misses": summary.misses,
        "pushes": summary.pushes,
        "skipped": summary.skipped,
        "elapsed_seconds": round(summary.elapsed_seconds, 3),
    }


def _resolve_player_game_batting_backfill_request(
    request: PlayerGameBattingBackfillRequest | None,
) -> ResolvedPlayerGameBattingBackfillRequest:
    request = request or PlayerGameBattingBackfillRequest()
    limit_events = (
        request.limit_events
        if request.limit_events is not None
        else DEFAULT_PLAYER_GAME_BATTING_LIMIT_EVENTS
    )

    if request.slate_date is not None:
        return ResolvedPlayerGameBattingBackfillRequest(
            slate_date=request.slate_date,
            start_date=None,
            end_date=None,
            limit_events=limit_events,
            dry_run=request.dry_run,
        )

    if request.start_date is not None and request.end_date is not None:
        return ResolvedPlayerGameBattingBackfillRequest(
            slate_date=None,
            start_date=request.start_date,
            end_date=request.end_date,
            limit_events=limit_events,
            dry_run=request.dry_run,
        )

    today = _current_slate_date()
    return ResolvedPlayerGameBattingBackfillRequest(
        slate_date=None,
        start_date=today - timedelta(days=1),
        end_date=today,
        limit_events=limit_events,
        dry_run=request.dry_run,
    )


def _resolve_batter_hits_training_example_build_request(
    request: BatterHitsTrainingExampleBuildRequest | None,
) -> ResolvedBatterHitsTrainingExampleBuildRequest:
    request = request or BatterHitsTrainingExampleBuildRequest()
    limit = (
        request.limit
        if request.limit is not None
        else DEFAULT_BATTER_HITS_TRAINING_EXAMPLE_LIMIT
    )

    if request.slate_date is not None:
        return ResolvedBatterHitsTrainingExampleBuildRequest(
            slate_date=request.slate_date,
            start_date=None,
            end_date=None,
            limit=limit,
            dry_run=request.dry_run,
        )

    if request.start_date is not None and request.end_date is not None:
        return ResolvedBatterHitsTrainingExampleBuildRequest(
            slate_date=None,
            start_date=request.start_date,
            end_date=request.end_date,
            limit=limit,
            dry_run=request.dry_run,
        )

    today = _current_slate_date()
    return ResolvedBatterHitsTrainingExampleBuildRequest(
        slate_date=None,
        start_date=today - timedelta(days=1),
        end_date=today,
        limit=limit,
        dry_run=request.dry_run,
    )


def _current_slate_date() -> date:
    return datetime.now(UTC).astimezone(settings.slate_zoneinfo).date()


def _player_game_batting_summary(
    summary: PlayerGameBattingBackfillSummary,
    resolved_request: ResolvedPlayerGameBattingBackfillRequest,
) -> dict[str, Any]:
    return {
        "status": "completed",
        "resolved_window": {
            "slate_date": _optional_date_string(
                resolved_request.slate_date,
            ),
            "start_date": _optional_date_string(
                resolved_request.start_date,
            ),
            "end_date": _optional_date_string(resolved_request.end_date),
            "limit_events": resolved_request.limit_events,
            "dry_run": resolved_request.dry_run,
        },
        "events_found": summary.events_found,
        "events_processed": summary.events_processed,
        "player_rows_parsed": summary.player_rows_parsed,
        "player_rows_upserted": summary.player_rows_upserted,
        "skipped_events": summary.skipped_events,
        "skipped_players": summary.skipped_players,
        "elapsed_seconds": round(summary.elapsed_seconds, 3),
    }


def _batter_hits_training_example_build_summary(
    summary: FeatureBuildSummary,
    resolved_request: ResolvedBatterHitsTrainingExampleBuildRequest,
) -> dict[str, Any]:
    return {
        "status": "completed",
        "resolved_window": {
            "slate_date": _optional_date_string(
                resolved_request.slate_date,
            ),
            "start_date": _optional_date_string(
                resolved_request.start_date,
            ),
            "end_date": _optional_date_string(resolved_request.end_date),
            "limit": resolved_request.limit,
            "dry_run": resolved_request.dry_run,
        },
        "candidates_found": summary.candidates_found,
        "candidates_deduped": summary.candidates_deduped,
        "examples_built": summary.examples_built,
        "examples_upserted": summary.examples_upserted,
        "skipped_missing_label": summary.skipped_missing_label,
        "skipped_missing_history": summary.skipped_missing_history,
        "skipped_unsupported_side": summary.skipped_unsupported_side,
        "elapsed_seconds": round(summary.elapsed_seconds, 3),
    }


def _optional_date_string(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
