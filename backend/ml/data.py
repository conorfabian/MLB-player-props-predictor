from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, cast

import pandas as pd
from supabase import Client

from app.db import get_supabase

FEATURE_COLUMNS: tuple[str, ...] = (
    "line",
    "prior_games_3",
    "prior_games_5",
    "prior_games_10",
    "hits_last_3",
    "hits_last_5",
    "hits_last_10",
    "hit_rate_last_3",
    "hit_rate_last_5",
    "hit_rate_last_10",
    "avg_hits_last_10",
    "avg_at_bats_last_10",
    "avg_plate_appearances_last_10",
    "avg_total_bases_last_10",
    "strikeout_rate_last_10",
    "walk_rate_last_10",
    "season_games_before",
    "season_hits_before",
    "season_hit_rate_before",
    "season_avg_hits_before",
)

LEAKAGE_COLUMNS: frozenset[str] = frozenset(
    {
        "actual_hits",
        "target_over",
        "id",
        "prop_snapshot_id",
        "created_at",
        "updated_at",
        "commence_time",
        "game_date",
        "metadata",
    }
)

TARGET_COLUMN = "target_over"
DATE_COLUMN = "game_date"


def validate_feature_columns(
    feature_columns: Sequence[str] = FEATURE_COLUMNS,
) -> tuple[str, ...]:
    columns = tuple(feature_columns)
    leakage = sorted(set(columns) & LEAKAGE_COLUMNS)
    if leakage:
        raise ValueError(
            "Feature columns include leakage columns: "
            + ", ".join(leakage)
        )
    return columns


def load_batter_hits_training_examples(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    min_prior_games: int | None = None,
    limit: int | None = None,
    supabase: Client | None = None,
) -> pd.DataFrame:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("--start-date must be before or equal to --end-date.")
    if min_prior_games is not None and min_prior_games < 0:
        raise ValueError("--min-prior-games must be zero or greater.")
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be positive.")

    supabase = supabase or get_supabase()
    query = (
        supabase.table("batter_hits_training_examples")
        .select("*")
        .eq("sport_key", "baseball_mlb")
        .eq("market_key", "batter_hits")
        .eq("bookmaker_key", "prizepicks")
        .eq("side", "over")
        .order("game_date")
        .order("commence_time")
        .order("id")
    )
    if start_date is not None:
        query = query.gte("game_date", start_date.isoformat())
    if end_date is not None:
        query = query.lte("game_date", end_date.isoformat())
    if min_prior_games is not None:
        query = query.gte("season_games_before", min_prior_games)
    if limit is not None:
        query = query.limit(limit)

    rows = cast(list[dict[str, Any]], query.execute().data or [])
    return training_examples_frame(rows)


def training_examples_frame(rows: Sequence[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(list(rows))
    if df.empty:
        return df

    if DATE_COLUMN in df:
        df[DATE_COLUMN] = pd.to_datetime(df[DATE_COLUMN]).dt.date
    if "commence_time" in df:
        df["commence_time"] = pd.to_datetime(df["commence_time"])
    if TARGET_COLUMN in df:
        df[TARGET_COLUMN] = df[TARGET_COLUMN].astype(bool)

    for column in FEATURE_COLUMNS:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df

