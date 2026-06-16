import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.db import get_supabase
from app.schemas import BoardResponse, PickResponse

load_dotenv()

app = FastAPI(
    title="MLB Props Predictor API",
    version="0.1.0",
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:3000",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
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

    boards = board_result.data or []

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
        for pick in (picks_result.data or [])
    ]

    return BoardResponse(
        slate_date=board["slate_date"],
        generated_at=board["generated_at"],
        model_version=board["model_version"],
        status=board["status"],
        picks=picks,
    )
