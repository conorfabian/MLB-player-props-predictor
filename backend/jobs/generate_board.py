from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import date

from app.domain import ScoredCandidate
from app.pipeline import (
    _latest_run_with_slate_candidates,
    board_draft_from_ranked,
    prepare_candidate_predictions,
    rank_board_candidates,
    run_board_generation,
)
from app.repositories import publish_daily_board
from app.settings import SettingsError

logger = logging.getLogger(__name__)

__all__ = [
    "_latest_run_with_slate_candidates",
    "board_draft_from_ranked",
    "prepare_candidate_predictions",
    "publish_daily_board",
    "rank_board_candidates",
]


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
        summary = run_board_generation(
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
        logger.exception("Board generation failed")
        return 1

    if args.dry_run:
        _print_board(summary.top_picks)

    print(
        "slate_date={slate_date} ingestion_run_id={ingestion_run_id} "
        "candidates={candidates} published={published} "
        "model_version={model_version} elapsed_seconds={elapsed:.3f}"
        .format(
            slate_date=summary.slate_date.isoformat(),
            ingestion_run_id=summary.ingestion_run_id,
            candidates=summary.candidates,
            published=summary.published,
            model_version=summary.model_version,
            elapsed=summary.elapsed_seconds,
        )
    )
    return 0


def _print_board(ranked: Sequence[ScoredCandidate]) -> None:
    for scored in ranked[:10]:
        candidate = scored.candidate
        print(
            "#{rank} {player} over {line} hits {prob:.4f} {away} @ {home}"
            .format(
                rank=scored.rank,
                player=candidate.player_name,
                line=candidate.line,
                prob=scored.predicted_probability,
                away=candidate.away_team,
                home=candidate.home_team,
            )
        )
if __name__ == "__main__":
    sys.exit(main())
