from __future__ import annotations

from datetime import UTC, datetime

from app.domain import NormalizationSummary, PropCandidate
from app.propline_models import PropLineEventOdds, compact_raw_payload

PROVIDER = "propline"
SPORT_KEY = "baseball_mlb"
BOOKMAKER_KEY = "prizepicks"
MARKET_KEY = "batter_hits"


def normalize_batter_hit_candidates(
    odds: PropLineEventOdds,
    *,
    captured_at: datetime,
    now: datetime | None = None,
) -> NormalizationSummary:
    captured_at = _as_utc(captured_at)
    now_utc = _as_utc(now or datetime.now(UTC))
    commence_time = _as_utc(odds.commence_time)

    if commence_time <= now_utc:
        return NormalizationSummary(candidates=[], skipped_started=1)

    candidates: list[PropCandidate] = []
    skipped_non_prizepicks = 0
    skipped_nonstandard_dfs = 0
    skipped_malformed = 0
    skipped_not_over = 0

    for bookmaker in odds.bookmakers:
        if bookmaker.key != BOOKMAKER_KEY:
            skipped_non_prizepicks += sum(
                len(market.outcomes) for market in bookmaker.markets
            )
            continue

        for market in bookmaker.markets:
            if market.key != MARKET_KEY:
                continue

            for outcome in market.outcomes:
                outcome_name = (outcome.name or "").strip().lower()
                if outcome_name != "over":
                    skipped_not_over += 1
                    continue

                player_name = (outcome.description or "").strip()
                line = _numeric_line(outcome.point)
                if not player_name or line is None:
                    skipped_malformed += 1
                    continue

                if not _is_standard_dfs_offer(outcome):
                    skipped_nonstandard_dfs += 1
                    continue

                candidates.append(
                    PropCandidate(
                        provider=PROVIDER,
                        provider_event_id=odds.id,
                        sport_key=odds.sport_key,
                        commence_time=commence_time,
                        home_team=odds.home_team.strip(),
                        away_team=odds.away_team.strip(),
                        bookmaker_key=bookmaker.key,
                        bookmaker_title=(
                            bookmaker.title.strip()
                            if bookmaker.title
                            else None
                        ),
                        market_key=market.key,
                        outcome_name=outcome_name,
                        player_name=player_name,
                        line=line,
                        price_american=outcome.price,
                        dfs_odds_type=(
                            outcome.dfs_odds_type.strip().lower()
                            if outcome.dfs_odds_type
                            else None
                        ),
                        market_last_update=_optional_utc(
                            market.last_update
                        ),
                        source_recorded_at=_optional_utc(
                            outcome.recorded_at
                        ),
                        source_book_updated_at=_optional_utc(
                            outcome.book_updated_at
                        ),
                        captured_at=captured_at,
                        raw_payload=compact_raw_payload(
                            bookmaker=bookmaker,
                            market=market,
                            outcome=outcome,
                        ),
                    )
                )

    return NormalizationSummary(
        candidates=candidates,
        skipped_non_prizepicks=skipped_non_prizepicks,
        skipped_nonstandard_dfs=skipped_nonstandard_dfs,
        skipped_malformed=skipped_malformed,
        skipped_not_over=skipped_not_over,
    )


def _is_standard_dfs_offer(outcome: object) -> bool:
    dfs_odds_type = getattr(outcome, "dfs_odds_type", None)
    if dfs_odds_type:
        return str(dfs_odds_type).strip().lower() == "standard"

    joined = " ".join(
        str(value or "")
        for value in (
            getattr(outcome, "name", None),
            getattr(outcome, "description", None),
            getattr(outcome, "book_version", None),
        )
    ).lower()
    return "goblin" not in joined and "demon" not in joined


def _numeric_line(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _as_utc(value)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
