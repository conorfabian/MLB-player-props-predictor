from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Any

from supabase import Client

from app.db import get_supabase
from app.repositories import get_published_board_rows

RESULT_STATUSES = (
    "hit",
    "miss",
    "push",
    "pending",
    "postponed",
    "canceled",
)
TOP_K_VALUES = (1, 3, 5, 10)


def get_performance_summary(
    *,
    days: int = 30,
    limit_slates: int | None = None,
    today: date | None = None,
    supabase: Client | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    start_date = today - timedelta(days=days - 1)
    rows = get_published_board_rows(
        supabase or get_supabase(),
        start_date=start_date,
        end_date=today,
        limit=limit_slates,
    )
    return performance_summary_from_board_rows(
        rows,
        requested_start_date=start_date,
        requested_end_date=today,
        days=days,
        limit_slates=limit_slates,
    )


def get_recent_results(
    *,
    limit: int = 7,
    supabase: Client | None = None,
) -> dict[str, Any]:
    rows = get_published_board_rows(supabase or get_supabase(), limit=limit)
    return recent_results_from_board_rows(rows)


def performance_summary_from_board_rows(
    rows: list[dict[str, Any]],
    *,
    requested_start_date: date,
    requested_end_date: date,
    days: int,
    limit_slates: int | None,
) -> dict[str, Any]:
    slate_dates = [_parse_date(row["slate_date"]) for row in rows]
    all_picks = [pick for row in rows for pick in row.get("picks", [])]
    counts = _status_counts(all_picks)
    by_rank = [_rank_summary(rank, all_picks) for rank in range(1, 11)]
    graded_rows = [row for row in rows if _board_has_graded_pick(row)]
    graded_dates = [_parse_date(row["slate_date"]) for row in graded_rows]

    return {
        "requested_window": {
            "start_date": requested_start_date.isoformat(),
            "end_date": requested_end_date.isoformat(),
            "days": days,
            "limit_slates": limit_slates,
        },
        "data_date_range": {
            "start_date": min(slate_dates).isoformat() if slate_dates else None,
            "end_date": max(slate_dates).isoformat() if slate_dates else None,
        },
        "total_slates": len(rows),
        "graded_slates": len(graded_rows),
        "total_picks": len(all_picks),
        "settled_picks": counts["hit"] + counts["miss"] + counts["push"],
        "decision_picks": counts["hit"] + counts["miss"],
        "hits": counts["hit"],
        "misses": counts["miss"],
        "pushes": counts["push"],
        "pending": counts["pending"],
        "postponed": counts["postponed"],
        "canceled": counts["canceled"],
        "hit_rate": _hit_rate(counts["hit"], counts["miss"]),
        "top_k": {
            f"top_{top_k}_hit_rate": _top_k_hit_rate(all_picks, top_k)
            for top_k in TOP_K_VALUES
        },
        "by_rank": by_rank,
        "latest_graded_slate_date": (
            max(graded_dates).isoformat() if graded_dates else None
        ),
        "model_versions": sorted(
            {
                str(row["model_version"])
                for row in rows
                if row.get("model_version") is not None
            }
        ),
    }


def recent_results_from_board_rows(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "boards": [
            {
                "slate_date": row["slate_date"],
                "model_version": row["model_version"],
                "status": row["status"],
                "picks": [_recent_pick(pick) for pick in row.get("picks", [])],
                "summary": _recent_board_summary(row.get("picks", [])),
            }
            for row in sorted(
                rows,
                key=lambda item: _parse_date(item["slate_date"]),
                reverse=True,
            )
        ]
    }


def _recent_pick(pick: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": pick["rank"],
        "player_name": pick["player_name"],
        "team": pick["team"],
        "opponent": pick["opponent"],
        "prop_type": pick["prop_type"],
        "line": pick["line"],
        "side": pick["side"],
        "model_probability": pick["model_probability"],
        "game_time": pick.get("game_time"),
        "result_status": pick["result_status"],
        "actual_value": pick.get("actual_value"),
        "graded_at": pick.get("graded_at"),
    }


def _recent_board_summary(picks: list[dict[str, Any]]) -> dict[str, Any]:
    counts = _status_counts(picks)
    return {
        "hits": counts["hit"],
        "misses": counts["miss"],
        "pushes": counts["push"],
        "pending": counts["pending"],
        "decision_picks": counts["hit"] + counts["miss"],
        "hit_rate": _hit_rate(counts["hit"], counts["miss"]),
    }


def _rank_summary(rank: int, picks: list[dict[str, Any]]) -> dict[str, Any]:
    rank_picks = [pick for pick in picks if int(pick["rank"]) == rank]
    counts = _status_counts(rank_picks)
    return {
        "rank": rank,
        "hits": counts["hit"],
        "misses": counts["miss"],
        "pushes": counts["push"],
        "hit_rate": _hit_rate(counts["hit"], counts["miss"]),
    }


def _top_k_hit_rate(
    picks: list[dict[str, Any]],
    top_k: int,
) -> float | None:
    counts = _status_counts(
        [pick for pick in picks if int(pick["rank"]) <= top_k]
    )
    return _hit_rate(counts["hit"], counts["miss"])


def _status_counts(picks: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for pick in picks:
        status = str(pick.get("result_status", "pending"))
        if status in RESULT_STATUSES:
            counts[status] += 1
    return counts


def _board_has_graded_pick(row: dict[str, Any]) -> bool:
    return any(
        pick.get("result_status") in {"hit", "miss", "push"}
        for pick in row.get("picks", [])
    )


def _hit_rate(hits: int, misses: int) -> float | None:
    denominator = hits + misses
    if denominator == 0:
        return None
    return hits / denominator


def _parse_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)
