from typing import Any

from fastapi.testclient import TestClient

import app.main as main


class FakeResult:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class FakeQuery:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data

    def select(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        return self

    def execute(self) -> FakeResult:
        return FakeResult(self.data)


class FakeSupabase:
    def __init__(
        self,
        boards: list[dict[str, Any]],
        picks: list[dict[str, Any]],
    ) -> None:
        self.boards = boards
        self.picks = picks

    def table(self, name: str) -> FakeQuery:
        if name == "daily_boards":
            return FakeQuery(self.boards)

        if name == "board_picks":
            return FakeQuery(self.picks)

        raise AssertionError(f"Unexpected table: {name}")


def test_get_latest_board(monkeypatch: Any) -> None:
    fake_supabase = FakeSupabase(
        boards=[
            {
                "id": 1,
                "slate_date": "2026-06-16",
                "generated_at": "2026-06-16T21:44:23.937112+00:00",
                "model_version": "skeleton-v0",
                "status": "published",
            }
        ],
        picks=[
            {
                "rank": 1,
                "player_name": "Test Player",
                "team": "LAD",
                "opponent": "SD",
                "prop_type": "hits",
                "line": 0.5,
                "side": "over",
                "model_probability": 0.712,
                "game_time": "2026-06-17T01:44:23.937112+00:00",
                "result_status": "pending",
                "actual_value": None,
                "graded_at": None,
            }
        ],
    )
    monkeypatch.setattr(main, "get_supabase", lambda: fake_supabase)
    client = TestClient(main.app)

    response = client.get("/api/boards/latest")

    assert response.status_code == 200
    data = response.json()
    assert data["model_version"] == "skeleton-v0"
    assert data["status"] == "published"
    assert len(data["picks"]) == 1
    assert data["picks"][0]["player_name"] == "Test Player"
    assert data["picks"][0]["actual_value"] is None


def test_get_latest_board_returns_404_when_no_board(monkeypatch: Any) -> None:
    fake_supabase = FakeSupabase(boards=[], picks=[])
    monkeypatch.setattr(main, "get_supabase", lambda: fake_supabase)
    client = TestClient(main.app)

    response = client.get("/api/boards/latest")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "No published board was found.",
    }
