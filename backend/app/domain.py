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


@dataclass(frozen=True)
class PlayerGameEventContext:
    provider: str
    provider_event_id: str
    sport_key: str
    game_date: date
    commence_time: datetime
    home_team: str | None
    away_team: str | None


@dataclass(frozen=True)
class PlayerGameBatting:
    provider: str
    provider_event_id: str
    sport_key: str
    game_date: date
    commence_time: datetime | None
    home_team: str | None
    away_team: str | None
    player_name: str
    normalized_player_name: str
    team: str | None
    opponent: str | None
    is_home: bool | None
    hits: int | None
    at_bats: int | None
    plate_appearances: int | None
    walks: int | None
    strikeouts: int | None
    total_bases: int | None
    rbis: int | None
    runs: int | None
    home_runs: int | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class BatterHitsFeatureRow:
    prior_games_3: int
    prior_games_5: int
    prior_games_10: int
    hits_last_3: int
    hits_last_5: int
    hits_last_10: int
    hit_rate_last_3: float | None
    hit_rate_last_5: float | None
    hit_rate_last_10: float | None
    avg_hits_last_10: float | None
    avg_at_bats_last_10: float | None
    avg_plate_appearances_last_10: float | None
    avg_total_bases_last_10: float | None
    strikeout_rate_last_10: float | None
    walk_rate_last_10: float | None
    season_games_before: int
    season_hits_before: int
    season_hit_rate_before: float | None
    season_avg_hits_before: float | None
    has_prior_batting_history: bool
    is_cold_start: bool


@dataclass(frozen=True)
class BatterHitsTrainingExample:
    prop_snapshot_id: int
    provider: str
    provider_event_id: str
    sport_key: str
    bookmaker_key: str
    market_key: str
    player_name: str
    normalized_player_name: str
    game_date: date
    commence_time: datetime | None
    home_team: str | None
    away_team: str | None
    line: float
    side: str
    actual_hits: int
    target_over: bool
    feature_version: str
    features: BatterHitsFeatureRow
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureBuildSummary:
    candidates_found: int
    candidates_deduped: int
    examples_built: int
    examples_upserted: int
    skipped_missing_label: int
    skipped_missing_history: int
    skipped_unsupported_side: int
    elapsed_seconds: float
