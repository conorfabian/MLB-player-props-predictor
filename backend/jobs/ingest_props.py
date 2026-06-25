from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from app.domain import PropCandidate
from app.pipeline import run_ingestion
from app.settings import SettingsError

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        summary = run_ingestion(dry_run=args.dry_run)
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        logger.exception("Prop ingestion failed")
        return 1

    if args.dry_run:
        _print_candidate_summary(summary.candidates)

    print(
        "run_id={run_id} events_found={events_found} "
        "events_processed={events_processed} "
        "offers_normalized={offers_normalized} offers_saved={offers_saved} "
        "skipped_non_prizepicks={skipped_non_prizepicks} "
        "skipped_nonstandard_dfs={skipped_nonstandard_dfs} "
        "skipped_malformed={skipped_malformed} "
        "elapsed_seconds={elapsed:.3f}".format(
            run_id=summary.run_id,
            events_found=summary.events_found,
            events_processed=summary.events_processed,
            offers_normalized=summary.offers_normalized,
            offers_saved=summary.offers_saved,
            skipped_non_prizepicks=summary.skipped_non_prizepicks,
            skipped_nonstandard_dfs=summary.skipped_nonstandard_dfs,
            skipped_malformed=summary.skipped_malformed,
            elapsed=summary.elapsed_seconds,
        )
    )
    return 0


def _print_candidate_summary(candidates: Sequence[PropCandidate]) -> None:
    for candidate in candidates[:20]:
        print(
            "{player} over {line} {away} @ {home} {time}".format(
                player=candidate.player_name,
                line=candidate.line,
                away=candidate.away_team,
                home=candidate.home_team,
                time=candidate.commence_time.isoformat(),
            )
        )
    if len(candidates) > 20:
        print(f"... {len(candidates) - 20} more candidates")


if __name__ == "__main__":
    sys.exit(main())
