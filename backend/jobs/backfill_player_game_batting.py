from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from app.player_game_batting import run_player_game_batting_backfill
from app.settings import SettingsError

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--slate-date")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--limit-events", type=int)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        summary = run_player_game_batting_backfill(
            dry_run=args.dry_run,
            slate_date=_optional_date(args.slate_date),
            start_date=_optional_date(args.start_date),
            end_date=_optional_date(args.end_date),
            limit_events=args.limit_events,
        )
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        logger.exception("Player-game batting backfill failed")
        return 1

    print(
        "events_found={events_found} events_processed={events_processed} "
        "player_rows_parsed={player_rows_parsed} "
        "player_rows_upserted={player_rows_upserted} "
        "skipped_events={skipped_events} skipped_players={skipped_players} "
        "elapsed_seconds={elapsed:.3f}".format(
            events_found=summary.events_found,
            events_processed=summary.events_processed,
            player_rows_parsed=summary.player_rows_parsed,
            player_rows_upserted=summary.player_rows_upserted,
            skipped_events=summary.skipped_events,
            skipped_players=summary.skipped_players,
            elapsed=summary.elapsed_seconds,
        )
    )
    return 0


def _optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


if __name__ == "__main__":
    sys.exit(main())
