from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.normalization import normalize_batter_hit_candidates
from app.propline_models import PropLineEventOdds
from tests.fixtures import odds_payload


def test_normalizer_filters_to_prizepicks_standard_overs() -> None:
    odds = PropLineEventOdds.model_validate(odds_payload())

    summary = normalize_batter_hit_candidates(
        odds,
        captured_at=datetime(2026, 6, 16, 18, 5, tzinfo=UTC),
        now=datetime.now(UTC),
    )

    names = {candidate.player_name for candidate in summary.candidates}
    assert "Valid Player 0" in names
    assert "Implicit Standard" in names
    assert "Other Book Player" not in names
    assert "Under Player" not in names
    assert "Goblin Player" not in names
    assert "Demon Player" not in names
    assert "No Point" not in names
    assert "Market demon 1.5" not in names
    assert summary.skipped_non_prizepicks == 1
    assert summary.skipped_nonstandard_dfs == 3
    assert summary.skipped_malformed == 2
    assert all(
        candidate.commence_time.tzinfo is not None
        and candidate.captured_at.tzinfo is not None
        for candidate in summary.candidates
    )


def test_normalizer_excludes_started_events() -> None:
    payload = odds_payload(
        commence_time=(datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    )
    odds = PropLineEventOdds.model_validate(payload)

    summary = normalize_batter_hit_candidates(
        odds,
        captured_at=datetime.now(UTC),
        now=datetime.now(UTC),
    )

    assert summary.candidates == []
    assert summary.skipped_started == 1
