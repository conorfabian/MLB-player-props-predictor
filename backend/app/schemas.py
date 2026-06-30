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
    actual_value: float | None = None
    graded_at: datetime | None = None


class BoardResponse(BaseModel):
    slate_date: date
    generated_at: datetime
    model_version: str
    status: str
    picks: list[PickResponse]


class RequestedPerformanceWindow(BaseModel):
    start_date: date
    end_date: date
    days: int
    limit_slates: int | None = None


class DataDateRange(BaseModel):
    start_date: date | None = None
    end_date: date | None = None


class TopKPerformance(BaseModel):
    top_1_hit_rate: float | None = None
    top_3_hit_rate: float | None = None
    top_5_hit_rate: float | None = None
    top_10_hit_rate: float | None = None


class RankPerformance(BaseModel):
    rank: int = Field(ge=1, le=10)
    hits: int
    misses: int
    pushes: int
    hit_rate: float | None = None


class PerformanceSummaryResponse(BaseModel):
    requested_window: RequestedPerformanceWindow
    data_date_range: DataDateRange
    total_slates: int
    graded_slates: int
    total_picks: int
    settled_picks: int
    decision_picks: int
    hits: int
    misses: int
    pushes: int
    pending: int
    postponed: int
    canceled: int
    hit_rate: float | None = None
    top_k: TopKPerformance
    by_rank: list[RankPerformance]
    latest_graded_slate_date: date | None = None
    model_versions: list[str]


class RecentBoardSummary(BaseModel):
    hits: int
    misses: int
    pushes: int
    pending: int
    decision_picks: int
    hit_rate: float | None = None


class RecentBoardResult(BaseModel):
    slate_date: date
    model_version: str
    status: str
    picks: list[PickResponse]
    summary: RecentBoardSummary


class RecentResultsResponse(BaseModel):
    boards: list[RecentBoardResult]
