from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain import PropCandidate


def odds_payload(
    *,
    event_id: str = "evt-1",
    commence_time: str | None = None,
) -> dict[str, Any]:
    commence_time = commence_time or (
        datetime.now(UTC) + timedelta(hours=4)
    ).isoformat()
    valid_outcomes = [
        {
            "name": "Over",
            "description": f"Valid Player {index}",
            "price": 100,
            "point": 0.5,
            "recorded_at": "2026-06-16T18:00:00Z",
            "book_updated_at": "2026-06-16T18:01:00Z",
            "dfs_odds_type": "standard",
        }
        for index in range(12)
    ]
    return {
        "id": event_id,
        "sport_key": "baseball_mlb",
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "commence_time": commence_time,
        "bookmakers": [
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "batter_hits",
                        "outcomes": [
                            {
                                "name": "Over",
                                "description": "Other Book Player",
                                "price": -120,
                                "point": 0.5,
                            }
                        ],
                    }
                ],
            },
            {
                "key": "prizepicks",
                "title": "PrizePicks",
                "markets": [
                    {
                        "key": "batter_hits",
                        "last_update": "2026-06-16T18:00:00Z",
                        "outcomes": valid_outcomes
                        + [
                            {
                                "name": "Under",
                                "description": "Under Player",
                                "price": 100,
                                "point": 0.5,
                                "dfs_odds_type": "standard",
                            },
                            {
                                "name": "Over",
                                "description": "Goblin Player",
                                "price": 100,
                                "point": 0.5,
                                "dfs_odds_type": "goblin",
                            },
                            {
                                "name": "Over",
                                "description": "Demon Player",
                                "price": 100,
                                "point": 1.5,
                                "dfs_odds_type": "demon",
                            },
                            {
                                "name": "Over",
                                "description": "",
                                "price": 100,
                                "point": 0.5,
                                "dfs_odds_type": "standard",
                            },
                            {
                                "name": "Over",
                                "description": "No Point",
                                "price": 100,
                                "dfs_odds_type": "standard",
                            },
                            {
                                "name": "Over",
                                "description": "Implicit Standard",
                                "price": 100,
                                "point": 0.5,
                            },
                            {
                                "name": "Over",
                                "description": "Market demon 1.5",
                                "price": 100,
                                "point": 1.5,
                            },
                        ],
                    }
                ],
            },
        ],
    }


def candidate(
    *,
    index: int = 1,
    line: float = 0.5,
    commence_time: datetime | None = None,
    snapshot_id: int | None = None,
) -> PropCandidate:
    return PropCandidate(
        id=snapshot_id or index,
        provider="propline",
        provider_event_id=f"evt-{index}",
        sport_key="baseball_mlb",
        commence_time=commence_time
        or datetime(2026, 6, 16, 23, 0, tzinfo=UTC),
        home_team="New York Yankees",
        away_team="Boston Red Sox",
        bookmaker_key="prizepicks",
        bookmaker_title="PrizePicks",
        market_key="batter_hits",
        outcome_name="over",
        player_name=f"Player {index}",
        line=line,
        price_american=100,
        dfs_odds_type="standard",
        market_last_update=None,
        source_recorded_at=None,
        source_book_updated_at=None,
        captured_at=datetime(2026, 6, 16, 18, 0, tzinfo=UTC),
        raw_payload={"fixture": True},
    )
