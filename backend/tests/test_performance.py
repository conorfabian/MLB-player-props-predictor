from __future__ import annotations

from datetime import date
from typing import Any

from fastapi.testclient import TestClient

from app import main
from app.performance import (
    performance_summary_from_board_rows,
    recent_results_from_board_rows,
)
from app.repositories import get_published_board_rows


class FakeResult:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class FakeQuery:
    def __init__(
        self,
        supabase: "FakeSupabase",
        table_name: str,
        data: list[dict[str, Any]],
    ) -> None:
        self.supabase = supabase
        self.table_name = table_name
        self.data = data
        self.board_ids: list[int] | None = None
        self.order_by: list[tuple[str, bool]] = []

    def select(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        return self

    def gte(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        return self

    def lte(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        return self

    def in_(self, column: str, values: list[int]) -> "FakeQuery":
        assert column == "board_id"
        self.board_ids = values
        self.supabase.board_pick_in_values = values
        return self

    def order(
        self,
        column: str,
        *,
        desc: bool = False,
    ) -> "FakeQuery":
        self.order_by.append((column, desc))
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        return self

    def execute(self) -> FakeResult:
        rows = list(self.data)
        if self.table_name == "board_picks" and self.board_ids is not None:
            rows = [
                row for row in rows if row["board_id"] in self.board_ids
            ]
        for column, desc in reversed(self.order_by):
            rows.sort(key=lambda row: row[column], reverse=desc)
        return FakeResult(rows)


class FakeSupabase:
    def __init__(
        self,
        boards: list[dict[str, Any]],
        picks: list[dict[str, Any]],
    ) -> None:
        self.boards = boards
        self.picks = picks
        self.table_calls: list[str] = []
        self.board_pick_in_values: list[int] | None = None

    def table(self, name: str) -> FakeQuery:
        self.table_calls.append(name)
        if name == "daily_boards":
            return FakeQuery(self, name, self.boards)
        if name == "board_picks":
            return FakeQuery(self, name, self.picks)
        raise AssertionError(f"Unexpected table: {name}")


def test_performance_summary_empty_dataset() -> None:
    summary = performance_summary_from_board_rows(
        [],
        requested_start_date=date(2026, 6, 1),
        requested_end_date=date(2026, 6, 30),
        days=30,
        limit_slates=None,
    )

    assert summary["requested_window"] == {
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
        "days": 30,
        "limit_slates": None,
    }
    assert summary["data_date_range"] == {
        "start_date": None,
        "end_date": None,
    }
    assert summary["total_slates"] == 0
    assert summary["graded_slates"] == 0
    assert summary["total_picks"] == 0
    assert summary["settled_picks"] == 0
    assert summary["decision_picks"] == 0
    assert summary["hit_rate"] is None
    assert summary["top_k"] == {
        "top_1_hit_rate": None,
        "top_3_hit_rate": None,
        "top_5_hit_rate": None,
        "top_10_hit_rate": None,
    }
    assert summary["latest_graded_slate_date"] is None
    assert summary["model_versions"] == []


def test_performance_summary_counts_statuses_and_rates() -> None:
    rows = [
        _board(
            slate_date="2026-06-03",
            model_version="placeholder-v0",
            statuses=[
                "hit",
                "miss",
                "push",
                "pending",
                "postponed",
                "canceled",
                "hit",
                "miss",
                "pending",
                "push",
            ],
        ),
        _board(
            slate_date="2026-06-02",
            model_version="baseline-v0",
            statuses=["pending"] * 10,
        ),
        _board(
            slate_date="2026-06-01",
            model_version="placeholder-v0",
            statuses=["hit", "hit", "miss"] + ["pending"] * 7,
        ),
    ]

    summary = performance_summary_from_board_rows(
        rows,
        requested_start_date=date(2026, 6, 1),
        requested_end_date=date(2026, 6, 30),
        days=30,
        limit_slates=3,
    )

    assert summary["data_date_range"] == {
        "start_date": "2026-06-01",
        "end_date": "2026-06-03",
    }
    assert summary["total_slates"] == 3
    assert summary["graded_slates"] == 2
    assert summary["total_picks"] == 30
    assert summary["settled_picks"] == 9
    assert summary["decision_picks"] == 7
    assert summary["hits"] == 4
    assert summary["misses"] == 3
    assert summary["pushes"] == 2
    assert summary["pending"] == 19
    assert summary["postponed"] == 1
    assert summary["canceled"] == 1
    assert summary["hit_rate"] == 4 / 7
    assert summary["latest_graded_slate_date"] == "2026-06-03"
    assert summary["model_versions"] == ["baseline-v0", "placeholder-v0"]


def test_top_k_and_by_rank_exclude_push_and_pending_denominators() -> None:
    rows = [
        _board(
            slate_date="2026-06-01",
            statuses=[
                "hit",
                "miss",
                "push",
                "pending",
                "hit",
                "miss",
                "pending",
                "push",
                "hit",
                "miss",
            ],
        )
    ]

    summary = performance_summary_from_board_rows(
        rows,
        requested_start_date=date(2026, 6, 1),
        requested_end_date=date(2026, 6, 30),
        days=30,
        limit_slates=None,
    )

    assert summary["top_k"] == {
        "top_1_hit_rate": 1.0,
        "top_3_hit_rate": 0.5,
        "top_5_hit_rate": 2 / 3,
        "top_10_hit_rate": 3 / 6,
    }
    by_rank = {item["rank"]: item for item in summary["by_rank"]}
    assert by_rank[1]["hit_rate"] == 1.0
    assert by_rank[2]["hit_rate"] == 0.0
    assert by_rank[3]["pushes"] == 1
    assert by_rank[3]["hit_rate"] is None
    assert by_rank[4]["hit_rate"] is None


def test_recent_results_returns_boards_newest_first() -> None:
    results = recent_results_from_board_rows(
        [
            _board(slate_date="2026-06-01", statuses=["miss"]),
            _board(slate_date="2026-06-03", statuses=["hit"]),
            _board(slate_date="2026-06-02", statuses=["push"]),
        ]
    )

    assert [
        board["slate_date"] for board in results["boards"]
    ] == ["2026-06-03", "2026-06-02", "2026-06-01"]
    assert "id" not in results["boards"][0]
    assert "metadata" not in results["boards"][0]
    assert "grading_metadata" not in results["boards"][0]["picks"][0]
    assert results["boards"][0]["summary"]["hit_rate"] == 1.0
    assert results["boards"][1]["summary"]["hit_rate"] is None


def test_get_published_board_rows_fetches_and_groups_picks_in_bulk() -> None:
    supabase = FakeSupabase(
        boards=[
            _board_row(board_id=2, slate_date="2026-06-03"),
            _board_row(board_id=1, slate_date="2026-06-02"),
        ],
        picks=[
            _pick_row(board_id=1, rank=2, status="miss"),
            _pick_row(board_id=2, rank=2, status="pending"),
            _pick_row(board_id=1, rank=1, status="hit"),
            _pick_row(board_id=2, rank=1, status="push"),
            _pick_row(board_id=99, rank=1, status="hit"),
        ],
    )

    rows = get_published_board_rows(supabase)

    assert [row["id"] for row in rows] == [2, 1]
    assert supabase.table_calls == ["daily_boards", "board_picks"]
    assert supabase.board_pick_in_values == [2, 1]
    assert [[pick["rank"] for pick in row["picks"]] for row in rows] == [
        [1, 2],
        [1, 2],
    ]
    assert rows[0]["picks"][0]["result_status"] == "push"
    assert rows[1]["picks"][0]["result_status"] == "hit"
    assert "board_id" not in rows[0]["picks"][0]


def test_get_published_board_rows_handles_empty_boards_without_pick_query() -> None:
    supabase = FakeSupabase(boards=[], picks=[_pick_row(board_id=1, rank=1)])

    rows = get_published_board_rows(supabase)

    assert rows == []
    assert supabase.table_calls == ["daily_boards"]
    assert supabase.board_pick_in_values is None


def test_get_published_board_rows_returns_empty_picks_for_boards_with_no_picks() -> None:
    supabase = FakeSupabase(
        boards=[
            _board_row(board_id=2, slate_date="2026-06-03"),
            _board_row(board_id=1, slate_date="2026-06-02"),
        ],
        picks=[_pick_row(board_id=1, rank=1, status="hit")],
    )

    rows = get_published_board_rows(supabase)

    assert [pick["rank"] for pick in rows[0]["picks"]] == []
    assert [pick["rank"] for pick in rows[1]["picks"]] == [1]


def test_performance_summary_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        main,
        "get_performance_summary",
        lambda **kwargs: {
            "requested_window": {
                "start_date": "2026-06-24",
                "end_date": "2026-06-30",
                "days": kwargs["days"],
                "limit_slates": kwargs["limit_slates"],
            },
            "data_date_range": {
                "start_date": None,
                "end_date": None,
            },
            "total_slates": 0,
            "graded_slates": 0,
            "total_picks": 0,
            "settled_picks": 0,
            "decision_picks": 0,
            "hits": 0,
            "misses": 0,
            "pushes": 0,
            "pending": 0,
            "postponed": 0,
            "canceled": 0,
            "hit_rate": None,
            "top_k": {
                "top_1_hit_rate": None,
                "top_3_hit_rate": None,
                "top_5_hit_rate": None,
                "top_10_hit_rate": None,
            },
            "by_rank": [
                {
                    "rank": rank,
                    "hits": 0,
                    "misses": 0,
                    "pushes": 0,
                    "hit_rate": None,
                }
                for rank in range(1, 11)
            ],
            "latest_graded_slate_date": None,
            "model_versions": [],
        },
    )
    client = TestClient(main.app)

    response = client.get("/api/performance/summary?days=7&limit_slates=2")

    assert response.status_code == 200
    data = response.json()
    assert data["requested_window"]["days"] == 7
    assert data["requested_window"]["limit_slates"] == 2


def test_recent_results_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        main,
        "get_recent_results",
        lambda **kwargs: {"boards": [] if kwargs["limit"] == 3 else ["bad"]},
    )
    client = TestClient(main.app)

    response = client.get("/api/results/recent?limit=3")

    assert response.status_code == 200
    assert response.json() == {"boards": []}


def test_performance_summary_validation() -> None:
    client = TestClient(main.app)

    assert client.get("/api/performance/summary?days=0").status_code == 422
    assert client.get("/api/performance/summary?days=366").status_code == 422
    assert (
        client.get("/api/performance/summary?limit_slates=0").status_code
        == 422
    )
    assert (
        client.get("/api/performance/summary?limit_slates=366").status_code
        == 422
    )


def test_recent_results_validation() -> None:
    client = TestClient(main.app)

    assert client.get("/api/results/recent?limit=0").status_code == 422
    assert client.get("/api/results/recent?limit=31").status_code == 422


def _board(
    *,
    slate_date: str,
    statuses: list[str],
    model_version: str = "placeholder-v0",
) -> dict[str, Any]:
    return {
        "id": 1,
        "slate_date": slate_date,
        "generated_at": f"{slate_date}T15:00:00+00:00",
        "model_version": model_version,
        "status": "published",
        "metadata": {"private": True},
        "picks": [
            _pick(rank=rank, status=status)
            for rank, status in enumerate(statuses, start=1)
        ],
    }


def _board_row(*, board_id: int, slate_date: str) -> dict[str, Any]:
    return {
        "id": board_id,
        "slate_date": slate_date,
        "generated_at": f"{slate_date}T15:00:00+00:00",
        "model_version": "placeholder-v0",
        "status": "published",
    }


def _pick_row(
    *,
    board_id: int,
    rank: int,
    status: str = "pending",
) -> dict[str, Any]:
    return {
        "board_id": board_id,
        **_pick(rank=rank, status=status),
    }


def _pick(*, rank: int, status: str) -> dict[str, Any]:
    return {
        "id": rank,
        "rank": rank,
        "player_name": f"Player {rank}",
        "team": "NYY",
        "opponent": "BOS",
        "prop_type": "hits",
        "line": 0.5,
        "side": "over",
        "model_probability": 0.6,
        "game_time": "2026-06-01T23:00:00+00:00",
        "result_status": status,
        "actual_value": 1 if status == "hit" else None,
        "graded_at": (
            "2026-06-02T03:00:00+00:00"
            if status in {"hit", "miss", "push"}
            else None
        ),
        "metadata": {"private": True},
        "grading_metadata": {"private": True},
    }
