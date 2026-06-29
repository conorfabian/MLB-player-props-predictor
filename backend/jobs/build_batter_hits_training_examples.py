from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from app.features import run_batter_hits_training_example_build
from app.settings import SettingsError

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--slate-date")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        summary = run_batter_hits_training_example_build(
            dry_run=args.dry_run,
            slate_date=_optional_date(args.slate_date),
            start_date=_optional_date(args.start_date),
            end_date=_optional_date(args.end_date),
            limit=args.limit,
        )
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        logger.exception("Batter hits training example build failed")
        return 1

    print(
        "candidates_found={candidates_found} "
        "candidates_deduped={candidates_deduped} "
        "examples_built={examples_built} "
        "examples_upserted={examples_upserted} "
        "skipped_missing_label={skipped_missing_label} "
        "skipped_missing_history={skipped_missing_history} "
        "skipped_unsupported_side={skipped_unsupported_side} "
        "elapsed_seconds={elapsed:.3f}".format(
            candidates_found=summary.candidates_found,
            candidates_deduped=summary.candidates_deduped,
            examples_built=summary.examples_built,
            examples_upserted=summary.examples_upserted,
            skipped_missing_label=summary.skipped_missing_label,
            skipped_missing_history=summary.skipped_missing_history,
            skipped_unsupported_side=summary.skipped_unsupported_side,
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
