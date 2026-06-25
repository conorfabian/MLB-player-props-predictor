from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from time import perf_counter
from zoneinfo import ZoneInfo

from supabase import Client

from app.db import get_supabase
from app.domain import (
    BoardDraft,
    BoardPickDraft,
    IngestionRun,
    PropCandidate,
    ScoredCandidate,
)
from app.normalization import normalize_batter_hit_candidates
from app.propline_client import PropLineClient
from app.repositories import (
    create_ingestion_run,
    create_model_run,
    get_completed_ingestion_runs,
    get_eligible_snapshots_for_run,
    insert_candidate_predictions,
    insert_prop_snapshots,
    mark_ingestion_run_completed,
    mark_ingestion_run_failed,
    mark_model_run_completed,
    mark_model_run_failed,
    publish_daily_board,
)
from app.scoring import PlaceholderScorer, rank_candidates
from app.settings import Settings, get_api_settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionSummary:
    run_id: str
    events_found: int
    events_processed: int
    offers_normalized: int
    offers_saved: int
    skipped_non_prizepicks: int
    skipped_nonstandard_dfs: int
    skipped_malformed: int
    elapsed_seconds: float
    candidates: Sequence[PropCandidate]


@dataclass(frozen=True)
class BoardGenerationSummary:
    slate_date: date
    ingestion_run_id: str
    candidates: int
    published: int
    model_version: str
    elapsed_seconds: float
    top_picks: Sequence[ScoredCandidate]


@dataclass(frozen=True)
class DailyBoardJobSummary:
    ingestion: IngestionSummary
    board: BoardGenerationSummary


def run_ingestion(
    *,
    dry_run: bool = False,
    settings: Settings | None = None,
    supabase: Client | None = None,
    client_factory: Callable[[Settings], PropLineClient] = PropLineClient,
) -> IngestionSummary:
    settings = settings or get_settings()
    started = perf_counter()
    run_id = "dry-run"
    events_found = 0
    events_processed = 0
    offers_saved = 0
    skipped_non_prizepicks = 0
    skipped_nonstandard_dfs = 0
    skipped_malformed = 0
    all_candidates: list[PropCandidate] = []

    if dry_run:
        supabase = None
    elif supabase is None:
        supabase = get_supabase()

    try:
        if supabase is not None:
            run = create_ingestion_run(
                supabase,
                provider="propline",
                sport_key="baseball_mlb",
                market_key="batter_hits",
                bookmaker_key="prizepicks",
                metadata={"dry_run": False},
            )
            run_id = run.id

        captured_at = datetime.now(UTC)
        with client_factory(settings) as client:
            events = client.list_mlb_events()
            events_found = len(events)
            upcoming_events = [
                event
                for event in events
                if event.commence_time.astimezone(UTC) > captured_at
            ]

            for event in upcoming_events:
                odds = client.get_batter_hit_odds(event.id)
                events_processed += 1
                summary = normalize_batter_hit_candidates(
                    odds,
                    captured_at=captured_at,
                    now=captured_at,
                )
                all_candidates.extend(summary.candidates)
                skipped_non_prizepicks += summary.skipped_non_prizepicks
                skipped_nonstandard_dfs += summary.skipped_nonstandard_dfs
                skipped_malformed += summary.skipped_malformed

        if supabase is not None:
            inserted = insert_prop_snapshots(
                supabase,
                ingestion_run_id=run_id,
                candidates=all_candidates,
            )
            offers_saved = len(inserted)
            mark_ingestion_run_completed(
                supabase,
                run_id=run_id,
                events_found=events_found,
                events_processed=events_processed,
                offers_saved=offers_saved,
                metadata={
                    "skipped_non_prizepicks": skipped_non_prizepicks,
                    "skipped_nonstandard_dfs": skipped_nonstandard_dfs,
                    "skipped_malformed": skipped_malformed,
                },
            )

        elapsed = perf_counter() - started
        logger.info(
            "Prop ingestion finished",
            extra={
                "run_id": run_id,
                "events_found": events_found,
                "events_processed": events_processed,
                "offers_normalized": len(all_candidates),
                "offers_saved": offers_saved,
                "skipped_non_prizepicks": skipped_non_prizepicks,
                "skipped_nonstandard_dfs": skipped_nonstandard_dfs,
                "skipped_malformed": skipped_malformed,
                "elapsed_seconds": round(elapsed, 3),
            },
        )
        return IngestionSummary(
            run_id=run_id,
            events_found=events_found,
            events_processed=events_processed,
            offers_normalized=len(all_candidates),
            offers_saved=offers_saved,
            skipped_non_prizepicks=skipped_non_prizepicks,
            skipped_nonstandard_dfs=skipped_nonstandard_dfs,
            skipped_malformed=skipped_malformed,
            elapsed_seconds=elapsed,
            candidates=all_candidates,
        )
    except Exception as exc:
        logger.exception("Prop ingestion failed")
        if supabase is not None and run_id != "dry-run":
            mark_ingestion_run_failed(
                supabase,
                run_id=run_id,
                error_message=str(exc),
                events_found=events_found,
                events_processed=events_processed,
                offers_saved=offers_saved,
                metadata={
                    "skipped_non_prizepicks": skipped_non_prizepicks,
                    "skipped_nonstandard_dfs": skipped_nonstandard_dfs,
                    "skipped_malformed": skipped_malformed,
                },
            )
        raise


def run_board_generation(
    *,
    dry_run: bool = False,
    slate_date: date | None = None,
    settings: Settings | None = None,
    supabase: Client | None = None,
) -> BoardGenerationSummary:
    settings = settings or get_api_settings()
    now = datetime.now(UTC)
    target_slate = slate_date or now.astimezone(settings.slate_zoneinfo).date()
    started = perf_counter()
    supabase = supabase or get_supabase()
    model_run_id: str | None = None

    try:
        ingestion_run, candidates = _latest_run_with_slate_candidates(
            supabase=supabase,
            target_slate=target_slate,
            slate_timezone=settings.slate_zoneinfo,
            now=now,
        )

        scorer = PlaceholderScorer()
        predictions = prepare_candidate_predictions(
            candidates,
            scorer=scorer,
            now=now,
        )
        ranked = _eligible_ranked(predictions)
        top_picks = ranked[:10]

        if not dry_run:
            model_run = create_model_run(
                supabase,
                ingestion_run_id=ingestion_run.id,
                run_type="placeholder",
                model_version=scorer.model_version,
                feature_version=scorer.feature_version,
                metadata={"scores_are_placeholders": True},
            )
            model_run_id = model_run.id
            insert_candidate_predictions(
                supabase,
                model_run_id=model_run.id,
                scored_candidates=predictions,
            )
            board = board_draft_from_ranked(
                target_slate=target_slate,
                ranked=top_picks,
                model_run_id=model_run.id,
                model_version=scorer.model_version,
            )
            publish_daily_board(supabase, board=board)
            mark_model_run_completed(
                supabase,
                model_run_id=model_run.id,
                candidate_count=len(predictions),
                published_count=len(top_picks),
                metadata={
                    "scores_are_placeholders": True,
                    "published_slate_date": target_slate.isoformat(),
                },
            )

        elapsed = perf_counter() - started
        if len(top_picks) < 10:
            logger.warning(
                "Publishing fewer than 10 picks because only %s eligible "
                "live props were available",
                len(top_picks),
            )
        return BoardGenerationSummary(
            slate_date=target_slate,
            ingestion_run_id=ingestion_run.id,
            candidates=len(predictions),
            published=len(top_picks),
            model_version=scorer.model_version,
            elapsed_seconds=elapsed,
            top_picks=top_picks,
        )
    except Exception as exc:
        logger.exception("Board generation failed")
        if model_run_id:
            mark_model_run_failed(
                supabase,
                model_run_id=model_run_id,
                error_message=str(exc),
            )
        raise


def run_daily_board_job() -> DailyBoardJobSummary:
    ingestion = run_ingestion()
    board = run_board_generation()
    return DailyBoardJobSummary(ingestion=ingestion, board=board)


def _latest_run_with_slate_candidates(
    *,
    supabase: Client,
    target_slate: date,
    slate_timezone: ZoneInfo,
    now: datetime,
) -> tuple[IngestionRun, list[PropCandidate]]:
    completed_runs = get_completed_ingestion_runs(supabase)
    if not completed_runs:
        raise RuntimeError("No completed ingestion run was found.")

    for ingestion_run in completed_runs:
        candidates = get_eligible_snapshots_for_run(
            supabase,
            ingestion_run_id=ingestion_run.id,
            now=now,
        )
        slate_candidates = [
            candidate
            for candidate in candidates
            if candidate.commence_time.astimezone(slate_timezone).date()
            == target_slate
        ]
        if slate_candidates:
            return ingestion_run, slate_candidates

    raise RuntimeError(
        f"No completed ingestion run has upcoming candidates for {target_slate}."
    )


def prepare_candidate_predictions(
    candidates: list[PropCandidate],
    *,
    scorer: PlaceholderScorer,
    now: datetime,
) -> list[ScoredCandidate]:
    scored_by_candidate_id = {
        id(scored.candidate): scored
        for scored in scorer.score(candidates)
    }
    seen: set[tuple[str, str, str, float]] = set()
    eligible: list[ScoredCandidate] = []
    predictions: list[ScoredCandidate] = []

    for candidate in candidates:
        scored = scored_by_candidate_id[id(candidate)]
        exclusion_reason: str | None = None
        key = _candidate_identity(candidate)

        if candidate.commence_time <= now:
            exclusion_reason = "game_started"
        elif key in seen:
            exclusion_reason = "duplicate_candidate"
        else:
            seen.add(key)

        prediction = ScoredCandidate(
            candidate=candidate,
            predicted_probability=scored.predicted_probability,
            eligible=exclusion_reason is None,
            exclusion_reason=exclusion_reason,
        )
        predictions.append(prediction)
        if prediction.eligible:
            eligible.append(prediction)

    ranked_eligible = rank_candidates(eligible)
    rank_by_candidate_id = {
        id(scored.candidate): scored.rank
        for scored in ranked_eligible
    }
    return [
        ScoredCandidate(
            candidate=prediction.candidate,
            predicted_probability=prediction.predicted_probability,
            rank=rank_by_candidate_id.get(id(prediction.candidate)),
            eligible=prediction.eligible,
            exclusion_reason=prediction.exclusion_reason,
        )
        for prediction in predictions
    ]


def _candidate_identity(
    candidate: PropCandidate,
) -> tuple[str, str, str, float]:
    return (
        candidate.provider_event_id,
        candidate.player_name,
        candidate.outcome_name,
        candidate.line,
    )


def rank_board_candidates(
    candidates: list[PropCandidate],
    *,
    scorer: PlaceholderScorer,
    now: datetime | None = None,
) -> list[ScoredCandidate]:
    return _eligible_ranked(
        prepare_candidate_predictions(
            candidates,
            scorer=scorer,
            now=now or datetime.now(UTC),
        )
    )


def _eligible_ranked(
    predictions: list[ScoredCandidate],
) -> list[ScoredCandidate]:
    return sorted(
        (prediction for prediction in predictions if prediction.eligible),
        key=lambda prediction: prediction.rank or 0,
    )


def board_draft_from_ranked(
    *,
    target_slate: date,
    ranked: list[ScoredCandidate],
    model_run_id: str,
    model_version: str,
) -> BoardDraft:
    picks: list[BoardPickDraft] = []
    for scored in ranked:
        candidate = scored.candidate
        picks.append(
            BoardPickDraft(
                rank=scored.rank or len(picks) + 1,
                player_name=candidate.player_name,
                team="TBD",
                opponent=f"{candidate.away_team} @ {candidate.home_team}",
                prop_type="hits",
                line=candidate.line,
                side="over",
                model_probability=scored.predicted_probability,
                game_time=candidate.commence_time,
                result_status="pending",
                prop_snapshot_id=candidate.id,
                model_run_id=model_run_id,
                provider=candidate.provider,
                bookmaker_key=candidate.bookmaker_key,
                metadata={
                    "source": "PropLine PrizePicks batter_hits",
                    "scores_are_placeholders": True,
                    "player_team_unresolved": True,
                    "home_team": candidate.home_team,
                    "away_team": candidate.away_team,
                },
            )
        )

    return BoardDraft(
        slate_date=target_slate,
        model_version=model_version,
        status="published",
        picks=picks,
        metadata={
            "scores_are_placeholders": True,
            "feature_version": "none-v0",
        },
    )
