from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain import BoardDraft, IngestionRun, ScoredCandidate
from app.pipeline import _latest_run_with_slate_candidates
from app.scoring import PlaceholderScorer
from jobs.generate_board import (
    board_draft_from_ranked,
    prepare_candidate_predictions,
    rank_board_candidates,
)
from tests.fixtures import candidate


def test_board_generation_selects_top_10_from_12_candidates() -> None:
    candidates = [candidate(index=index) for index in range(12)]

    ranked = rank_board_candidates(
        candidates,
        scorer=PlaceholderScorer(),
        now=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
    )
    board = board_draft_from_ranked(
        target_slate=date(2026, 6, 16),
        ranked=ranked[:10],
        model_run_id="00000000-0000-0000-0000-000000000001",
        model_version="placeholder-v0",
    )

    assert len(ranked) == 12
    assert len(board.picks) == 10
    assert board.model_version == "placeholder-v0"
    assert [pick.rank for pick in board.picks] == list(range(1, 11))
    assert all(pick.metadata["scores_are_placeholders"] for pick in board.picks)


def test_board_generation_selects_all_when_fewer_than_10() -> None:
    candidates = [candidate(index=index) for index in range(5)]

    ranked = rank_board_candidates(
        candidates,
        scorer=PlaceholderScorer(),
        now=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
    )

    assert len(ranked[:10]) == 5


def test_board_generation_records_duplicate_exclusions() -> None:
    first = candidate(index=1, snapshot_id=1)
    duplicate = candidate(index=1, snapshot_id=2)
    started = candidate(
        index=3,
        snapshot_id=3,
        commence_time=datetime(2026, 6, 16, 11, 0, tzinfo=UTC),
    )

    predictions = prepare_candidate_predictions(
        [first, duplicate, started],
        scorer=PlaceholderScorer(),
        now=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
    )
    ranked = [prediction for prediction in predictions if prediction.eligible]

    assert len(predictions) == 3
    assert len(ranked) == 1
    assert predictions[1].exclusion_reason == "duplicate_candidate"
    assert predictions[2].exclusion_reason == "game_started"
    assert predictions[1].rank is None
    assert predictions[2].rank is None


def test_failed_publication_preserves_prior_board_by_not_mutating_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[BoardDraft] = []

    def fake_publish(*_args: object, board: BoardDraft) -> None:
        calls.append(board)
        raise RuntimeError("publish failed")

    import jobs.generate_board as generate_board

    monkeypatch.setattr(generate_board, "publish_daily_board", fake_publish)
    ranked = [
        ScoredCandidate(
            candidate=candidate(index=1),
            predicted_probability=0.7,
            rank=1,
        )
    ]
    board = board_draft_from_ranked(
        target_slate=date(2026, 6, 16),
        ranked=ranked,
        model_run_id="00000000-0000-0000-0000-000000000001",
        model_version="placeholder-v0",
    )

    with pytest.raises(RuntimeError):
        generate_board.publish_daily_board(object(), board=board)  # type: ignore[arg-type]

    assert len(calls) == 1


def test_selects_latest_completed_run_with_target_slate_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = [
        _run("latest-empty"),
        _run("older-with-candidates"),
    ]
    candidates_by_run = {
        "latest-empty": [],
        "older-with-candidates": [candidate(index=1)],
    }

    import app.pipeline as pipeline

    monkeypatch.setattr(
        pipeline,
        "get_completed_ingestion_runs",
        lambda _supabase: runs,
    )
    monkeypatch.setattr(
        pipeline,
        "get_eligible_snapshots_for_run",
        lambda _supabase, *, ingestion_run_id, now: candidates_by_run[
            ingestion_run_id
        ],
    )

    selected_run, selected_candidates = _latest_run_with_slate_candidates(
        supabase=object(),  # type: ignore[arg-type]
        target_slate=date(2026, 6, 16),
        slate_timezone=ZoneInfo("America/New_York"),
        now=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
    )

    assert selected_run.id == "older-with-candidates"
    assert len(selected_candidates) == 1


def _run(run_id: str) -> IngestionRun:
    return IngestionRun(
        id=run_id,
        provider="propline",
        sport_key="baseball_mlb",
        market_key="batter_hits",
        bookmaker_key="prizepicks",
        started_at=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
        completed_at=datetime(2026, 6, 16, 12, 5, tzinfo=UTC),
        status="completed",
        events_found=1,
        events_processed=1,
        offers_saved=1,
        error_message=None,
        metadata={},
    )
