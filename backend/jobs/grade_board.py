from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from app.grading import run_board_grading
from app.settings import SettingsError

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--slate-date")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        target_slate = (
            date.fromisoformat(args.slate_date)
            if args.slate_date
            else None
        )
        summary = run_board_grading(
            dry_run=args.dry_run,
            slate_date=target_slate,
        )
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Invalid --slate-date: {exc}", file=sys.stderr)
        return 1
    except Exception:
        logger.exception("Board grading failed")
        return 1

    print(
        "graded={graded} still_pending={still_pending} hits={hits} "
        "misses={misses} pushes={pushes} skipped={skipped} "
        "elapsed_seconds={elapsed:.3f}".format(
            graded=summary.graded,
            still_pending=summary.still_pending,
            hits=summary.hits,
            misses=summary.misses,
            pushes=summary.pushes,
            skipped=summary.skipped,
            elapsed=summary.elapsed_seconds,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
