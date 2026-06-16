from datetime import date, datetime

from pydantic import BaseModel, Field


class PickResponse(BaseModel):
    rank: int = Field(ge=1, le=10)
    player_name: str
    team: str
    opponent: str
    prop_type: str
    line: float
    side: str
    model_probability: float = Field(ge=0.0, le=1.0)
    game_time: datetime | None
    result_status: str


class BoardResponse(BaseModel):
    slate_date: date
    generated_at: datetime
    model_version: str
    status: str
    picks: list[PickResponse]
