from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any, cast

from pydantic import ValidationError

from app.domain import PlayerGameBatting, PlayerGameEventContext
from app.propline_models import PropLineEventStats, PropLineStatsPlayer

FINAL_STATUSES = {"closed", "complete", "completed", "final", "finished"}
NOT_FINAL_STATUSES = {
    "created",
    "delayed",
    "in_progress",
    "live",
    "postponed",
    "pre",
    "scheduled",
    "started",
    "upcoming",
}

STAT_ALIASES: dict[str, tuple[str, ...]] = {
    "hits": ("hits", "hit", "h"),
    "at_bats": ("at_bats", "atbats", "ab"),
    "plate_appearances": (
        "plate_appearances",
        "plateappearances",
        "pa",
    ),
    "walks": ("walks", "walk", "bb"),
    "strikeouts": ("strikeouts", "strikeout", "so", "k"),
    "total_bases": ("total_bases", "totalbases", "tb"),
    "rbis": ("rbis", "rbi"),
    "runs": ("runs", "run", "r"),
    "home_runs": ("home_runs", "homeruns", "home_run", "homerun", "hr"),
}

CONTEXT_STAT_KEYS = {
    "at_bats",
    "plate_appearances",
    "walks",
    "strikeouts",
    "total_bases",
    "rbis",
    "runs",
    "home_runs",
}


def normalize_player_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_name.lower())


def extract_int_stat(
    stats: dict[str, Any] | None,
    candidate_keys: list[str] | tuple[str, ...],
) -> int | None:
    if not stats:
        return None

    normalized_lookup = {
        _normalize_stat_key(key): value
        for key, value in stats.items()
        if isinstance(key, str)
    }
    for key in candidate_keys:
        parsed = _numeric_int(normalized_lookup.get(_normalize_stat_key(key)))
        if parsed is not None:
            return parsed
    return None


def parse_player_game_batting(
    event_stats: PropLineEventStats,
    event_context: PlayerGameEventContext,
) -> list[PlayerGameBatting]:
    rows: list[PlayerGameBatting] = []
    seen: set[str] = set()
    grouped_flat_rows = _flat_rows_by_player(event_stats)

    for player in _iter_player_objects(event_stats):
        player_name = _player_name(player)
        normalized_name = normalize_player_name(player_name)
        if not player_name or not normalized_name or normalized_name in seen:
            continue

        flat_stats = grouped_flat_rows.get(normalized_name, {})
        stats = _combined_stats(player, flat_stats)
        parsed = _row_from_stats(
            player_name=player_name,
            normalized_name=normalized_name,
            stats=stats,
            raw_payload=player.model_dump(mode="json"),
            event_context=event_context,
            team=_player_team(player),
        )
        if parsed is not None:
            rows.append(parsed)
            seen.add(normalized_name)

    for normalized_name, flat_stats in grouped_flat_rows.items():
        if normalized_name in seen:
            continue
        player_name = cast(str, flat_stats.get("_player_name") or "")
        parsed = _row_from_stats(
            player_name=player_name,
            normalized_name=normalized_name,
            stats=flat_stats,
            raw_payload=cast(dict[str, Any], flat_stats.get("_raw") or {}),
            event_context=event_context,
            team=cast(str | None, flat_stats.get("_team")),
        )
        if parsed is not None:
            rows.append(parsed)
            seen.add(normalized_name)

    return rows


def count_player_stat_candidates(event_stats: PropLineEventStats) -> int:
    names: set[str] = set()
    for player in _iter_player_objects(event_stats):
        normalized = normalize_player_name(_player_name(player))
        if normalized:
            names.add(normalized)
    names.update(_flat_rows_by_player(event_stats))
    return len(names)


def is_event_final(stats_response: PropLineEventStats) -> bool:
    if stats_response.completed is True:
        return True
    if stats_response.completed is False:
        return False

    status = _event_status(stats_response)
    if status in FINAL_STATUSES:
        return True
    if status in NOT_FINAL_STATUSES:
        return False
    return False


def iter_stats_players(
    stats_response: PropLineEventStats,
) -> Iterable[PropLineStatsPlayer]:
    yield from _iter_player_objects(stats_response)


def player_name_from_stats(player: PropLineStatsPlayer) -> str:
    return _player_name(player)


def player_hits_from_stats(player: PropLineStatsPlayer) -> int | None:
    return _player_hits(player)


def extra_value(model: Any, key: str) -> Any:
    return _extra(model, key)


def numeric_int(value: Any) -> int | None:
    return _numeric_int(value)


def stat_value(stats: dict[str, Any] | None, key: str) -> Any:
    if not stats:
        return None
    return stats.get(key)


def _row_from_stats(
    *,
    player_name: str,
    normalized_name: str,
    stats: dict[str, Any],
    raw_payload: dict[str, Any],
    event_context: PlayerGameEventContext,
    team: str | None,
) -> PlayerGameBatting | None:
    values = {
        stat_name: extract_int_stat(stats, aliases)
        for stat_name, aliases in STAT_ALIASES.items()
    }
    if values["hits"] is None and not any(
        values[key] is not None for key in CONTEXT_STAT_KEYS
    ):
        return None

    is_home = _is_home_team(team, event_context)
    opponent = _opponent_for(team, is_home, event_context)
    return PlayerGameBatting(
        provider=event_context.provider,
        provider_event_id=event_context.provider_event_id,
        sport_key=event_context.sport_key,
        game_date=event_context.game_date,
        commence_time=event_context.commence_time,
        home_team=event_context.home_team,
        away_team=event_context.away_team,
        player_name=player_name,
        normalized_player_name=normalized_name,
        team=team,
        opponent=opponent,
        is_home=is_home,
        hits=values["hits"],
        at_bats=values["at_bats"],
        plate_appearances=values["plate_appearances"],
        walks=values["walks"],
        strikeouts=values["strikeouts"],
        total_bases=values["total_bases"],
        rbis=values["rbis"],
        runs=values["runs"],
        home_runs=values["home_runs"],
        raw_payload=raw_payload or {},
    )


def _iter_player_objects(
    stats_response: PropLineEventStats,
) -> Iterable[PropLineStatsPlayer]:
    if stats_response.players:
        yield from stats_response.players

    for key in ("player_stats", "stats", "boxscore"):
        value = _extra(stats_response, key)
        if isinstance(value, list):
            yield from _validate_players(value)
        elif isinstance(value, dict):
            for nested_key in ("players", "player_stats", "batters"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    yield from _validate_players(nested)


def _validate_players(values: list[Any]) -> Iterable[PropLineStatsPlayer]:
    for value in values:
        try:
            yield PropLineStatsPlayer.model_validate(value)
        except ValidationError:
            continue


def _flat_rows_by_player(
    stats_response: PropLineEventStats,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in _iter_flat_rows(stats_response):
        player_name = _flat_player_name(row)
        normalized_name = normalize_player_name(player_name)
        stat_type = row.get("stat_type") or row.get("type") or row.get("key")
        if not player_name or not normalized_name or not isinstance(
            stat_type,
            str,
        ):
            continue

        group = grouped.setdefault(
            normalized_name,
            {
                "_player_name": player_name,
                "_raw": {"rows": []},
                "_team": _flat_team(row),
            },
        )
        cast(dict[str, list[dict[str, Any]]], group["_raw"])["rows"].append(row)
        group[_normalize_stat_key(stat_type)] = (
            row.get("stat_value")
            if "stat_value" in row
            else row.get("value")
        )
        if group.get("_team") is None:
            group["_team"] = _flat_team(row)
    return grouped


def _iter_flat_rows(stats_response: PropLineEventStats) -> Iterable[dict[str, Any]]:
    for key in ("stats", "player_stats"):
        value = _extra(stats_response, key)
        if isinstance(value, list):
            yield from _dict_items(value)

    boxscore = _extra(stats_response, "boxscore")
    if isinstance(boxscore, dict):
        for key in ("stats", "player_stats", "batting"):
            value = boxscore.get(key)
            if isinstance(value, list):
                yield from _dict_items(value)


def _dict_items(values: list[Any]) -> Iterable[dict[str, Any]]:
    for value in values:
        if isinstance(value, dict):
            yield value


def _combined_stats(
    player: PropLineStatsPlayer,
    flat_stats: dict[str, Any],
) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for source in (
        player.stats,
        cast(dict[str, Any] | None, _extra(player, "batting")),
        player.model_extra,
        flat_stats,
    ):
        if isinstance(source, dict):
            stats.update(source)

    if player.hits is not None:
        stats["hits"] = player.hits
    return stats


def _player_name(player: PropLineStatsPlayer) -> str:
    for value in (
        player.name,
        player.player_name,
        player.description,
        _extra(player, "full_name"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _player_team(player: PropLineStatsPlayer) -> str | None:
    for value in (
        player.team,
        _extra(player, "team_name"),
        _extra(player, "team_abbreviation"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _player_hits(player: PropLineStatsPlayer) -> int | None:
    stat_type = _extra(player, "stat_type")
    if isinstance(stat_type, str) and _normalize_stat_key(stat_type) in {
        "h",
        "hits",
        "hit",
    }:
        parsed = _numeric_int(_extra(player, "stat_value"))
        if parsed is not None:
            return parsed

    stats = _combined_stats(player, {})
    return extract_int_stat(stats, STAT_ALIASES["hits"])


def _flat_player_name(row: dict[str, Any]) -> str:
    for key in ("player_name", "name", "description", "full_name"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _flat_team(row: dict[str, Any]) -> str | None:
    for key in ("team", "team_name", "team_abbreviation"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _event_status(stats_response: PropLineEventStats) -> str:
    for value in (
        stats_response.status,
        _extra(stats_response, "event_status"),
        _extra(stats_response, "game_status"),
        _extra(stats_response, "status_detail"),
    ):
        if isinstance(value, str):
            return value.strip().lower()
    return ""


def _is_home_team(
    team: str | None,
    event_context: PlayerGameEventContext,
) -> bool | None:
    if not team:
        return None
    normalized_team = team.strip().lower()
    if event_context.home_team and (
        normalized_team == event_context.home_team.strip().lower()
    ):
        return True
    if event_context.away_team and (
        normalized_team == event_context.away_team.strip().lower()
    ):
        return False
    return None


def _opponent_for(
    team: str | None,
    is_home: bool | None,
    event_context: PlayerGameEventContext,
) -> str | None:
    if is_home is True:
        return event_context.away_team
    if is_home is False:
        return event_context.home_team
    if team is None:
        return None
    return None


def _normalize_stat_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _numeric_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return int(parsed)


def _extra(model: Any, key: str) -> Any:
    extra = getattr(model, "model_extra", None) or {}
    return extra.get(key)
