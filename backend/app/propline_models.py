from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PropLineOutcome(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    description: str | None = None
    price: int | None = None
    point: float | int | str | None = None
    recorded_at: datetime | None = None
    book_updated_at: datetime | None = None
    book_version: str | None = None
    dfs_odds_type: str | None = None
    payout_multiplier: float | int | None = None


class PropLineMarket(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str
    last_update: datetime | None = None
    outcomes: list[PropLineOutcome] = []


class PropLineBookmaker(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str
    title: str | None = None
    markets: list[PropLineMarket] = []


class PropLineEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    sport_key: str
    home_team: str
    away_team: str
    commence_time: datetime
    live: bool | None = None
    completed: bool | None = None


class PropLineEventOdds(PropLineEvent):
    bookmakers: list[PropLineBookmaker] = []


def compact_raw_payload(
    *,
    bookmaker: PropLineBookmaker,
    market: PropLineMarket,
    outcome: PropLineOutcome,
) -> dict[str, Any]:
    return {
        "bookmaker": bookmaker.model_dump(mode="json", exclude={"markets"}),
        "market": market.model_dump(mode="json", exclude={"outcomes"}),
        "outcome": outcome.model_dump(mode="json"),
    }
