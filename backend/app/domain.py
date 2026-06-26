from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class PropCandidate:
    provider: str
    provider_event_id: str
    sport_key: str
    commence_time: datetime
    home_team: str
    away_team: str
    bookmaker_key: str
    bookmaker_title: str | None
    market_key: str
    outcome_name: str
    player_name: str
    line: float
    price_american: int | None
    dfs_odds_type: str | None
    market_last_update: datetime | None
    source_recorded_at: datetime | None
    source_book_updated_at: datetime | None
    captured_at: datetime
    raw_payload: dict[str, Any]
    id: int | None = None


@dataclass(frozen=True)
class NormalizationSummary:
    candidates: list[PropCandidate]
    skipped_non_prizepicks: int = 0
    skipped_nonstandard_dfs: int = 0
    skipped_malformed: int = 0
    skipped_not_over: int = 0
    skipped_started: int = 0


@dataclass(frozen=True)
class IngestionRun:
    id: str
    provider: str
    sport_key: str
    market_key: str
    bookmaker_key: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    events_found: int
    events_processed: int
    offers_saved: int
    error_message: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelRun:
    id: str
    ingestion_run_id: str
    run_type: str
    model_version: str
    feature_version: str
    status: str


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: PropCandidate
    predicted_probability: float
    rank: int | None = None
    eligible: bool = True
    exclusion_reason: str | None = None


@dataclass(frozen=True)
class BoardPickDraft:
    rank: int
    player_name: str
    team: str
    opponent: str
    prop_type: str
    line: float
    side: str
    model_probability: float
    game_time: datetime
    result_status: str
    prop_snapshot_id: int | None
    model_run_id: str | None
    provider: str
    bookmaker_key: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BoardDraft:
    slate_date: date
    model_version: str
    status: str
    picks: list[BoardPickDraft]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BoardPickForGrading:
    id: int
    board_id: int
    slate_date: date
    rank: int
    player_name: str
    prop_type: str
    line: float
    side: str
    game_time: datetime | None
    result_status: str
    prop_snapshot_id: int
    grading_metadata: dict[str, Any]
    snapshot: PropCandidate
