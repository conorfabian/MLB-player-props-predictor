from __future__ import annotations

from typing import Any

from app.repositories import (
    get_completed_ingestion_runs,
    insert_candidate_predictions,
    publish_daily_board,
)
from jobs.generate_board import board_draft_from_ranked
from tests.fixtures import candidate


class FakeResult:
    def __init__(self, data: list[dict[str, Any]] | None = None) -> None:
        self.data = data or []


class FakeTable:
    def __init__(self, data: list[dict[str, Any]] | None = None) -> None:
        self.inserted: list[Any] = []
        self.data = data or []
        self.limit_value: int | None = None

    def insert(self, payload: Any) -> "FakeTable":
        self.inserted.append(payload)
        return self

    def select(self, *_args: Any, **_kwargs: Any) -> "FakeTable":
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "FakeTable":
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> "FakeTable":
        return self

    def limit(self, value: int) -> "FakeTable":
        self.limit_value = value
        return self

    def execute(self) -> FakeResult:
        return FakeResult(self.data)


class FakeSupabase:
    def __init__(self) -> None:
        self.tables: dict[str, FakeTable] = {}
        self.rpc_calls: list[tuple[str, dict[str, Any]]] = []

    def table(self, name: str) -> FakeTable:
        table = self.tables.setdefault(name, FakeTable())
        return table

    def rpc(self, name: str, payload: dict[str, Any]) -> "FakeSupabase":
        self.rpc_calls.append((name, payload))
        return self

    def execute(self) -> FakeResult:
        return FakeResult([])


def test_repository_writes_all_candidate_predictions() -> None:
    fake = FakeSupabase()
    candidates = [candidate(index=index) for index in range(12)]
    scored = [
        type(
            "Scored",
            (),
            {
                "candidate": item,
                "predicted_probability": 0.6,
                "rank": index,
                "eligible": True,
                "exclusion_reason": None,
            },
        )()
        for index, item in enumerate(candidates, start=1)
    ]

    insert_candidate_predictions(
        fake,  # type: ignore[arg-type]
        model_run_id="00000000-0000-0000-0000-000000000001",
        scored_candidates=scored,  # type: ignore[arg-type]
    )

    inserted = fake.tables["candidate_predictions"].inserted[0]
    assert len(inserted) == 12


def test_publish_daily_board_uses_rpc() -> None:
    fake = FakeSupabase()
    ranked = [
        type(
            "Scored",
            (),
            {
                "candidate": candidate(index=1),
                "predicted_probability": 0.6,
                "rank": 1,
            },
        )()
    ]
    board = board_draft_from_ranked(
        target_slate=__import__("datetime").date(2026, 6, 16),
        ranked=ranked,  # type: ignore[arg-type]
        model_run_id="00000000-0000-0000-0000-000000000001",
        model_version="placeholder-v0",
    )

    publish_daily_board(fake, board=board)  # type: ignore[arg-type]

    assert fake.rpc_calls[0][0] == "publish_daily_board"
    assert fake.rpc_calls[0][1]["p_model_version"] == "placeholder-v0"
    assert len(fake.rpc_calls[0][1]["p_picks"]) == 1


def test_get_completed_ingestion_runs_defaults_to_no_limit() -> None:
    fake = FakeSupabase()
    fake.tables["prop_ingestion_runs"] = FakeTable(
        [
            {
                "id": "run-1",
                "provider": "propline",
                "sport_key": "baseball_mlb",
                "market_key": "batter_hits",
                "bookmaker_key": "prizepicks",
                "started_at": "2026-06-16T12:00:00+00:00",
                "completed_at": "2026-06-16T12:05:00+00:00",
                "status": "completed",
                "events_found": 1,
                "events_processed": 1,
                "offers_saved": 1,
                "error_message": None,
                "metadata": {},
            }
        ]
    )

    runs = get_completed_ingestion_runs(fake)  # type: ignore[arg-type]

    assert len(runs) == 1
    assert fake.tables["prop_ingestion_runs"].limit_value is None
