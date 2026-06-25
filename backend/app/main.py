import logging
import secrets
from threading import Lock
from typing import Any, cast

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.db import get_supabase
from app.pipeline import DailyBoardJobSummary, run_daily_board_job
from app.schemas import BoardResponse, PickResponse
from app.settings import get_api_settings

logger = logging.getLogger(__name__)

app = FastAPI(
    title="MLB Props Predictor API",
    version="0.1.0",
)

settings = get_api_settings()
job_lock = Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.frontend_origins),
    allow_credentials=False,
    allow_methods=["GET"],
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
            "game_time, result_status"
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
