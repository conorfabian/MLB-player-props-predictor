from __future__ import annotations

from app.domain import FeatureBuildSummary
from jobs import build_batter_hits_training_examples as job


def test_cli_passes_arguments_and_prints_summary(
    monkeypatch,
    capsys,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(**kwargs: object) -> FeatureBuildSummary:
        calls.append(kwargs)
        return FeatureBuildSummary(
            candidates_found=10,
            candidates_deduped=8,
            examples_built=7,
            examples_upserted=0,
            skipped_missing_label=1,
            skipped_missing_history=0,
            skipped_unsupported_side=0,
            elapsed_seconds=1.2345,
        )

    monkeypatch.setattr(job, "run_batter_hits_training_example_build", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "jobs.build_batter_hits_training_examples",
            "--dry-run",
            "--slate-date",
            "2026-06-16",
            "--limit",
            "50",
        ],
    )

    result = job.main()

    assert result == 0
    assert calls == [
        {
            "dry_run": True,
            "slate_date": __import__("datetime").date(2026, 6, 16),
            "start_date": None,
            "end_date": None,
            "limit": 50,
        }
    ]
    assert (
        "candidates_found=10 candidates_deduped=8 examples_built=7 "
        "examples_upserted=0 skipped_missing_label=1 "
        "skipped_missing_history=0 skipped_unsupported_side=0 "
        "elapsed_seconds=1.234"
    ) in capsys.readouterr().out


def test_cli_rejects_invalid_date(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "jobs.build_batter_hits_training_examples",
            "--slate-date",
            "not-a-date",
        ],
    )

    result = job.main()

    assert result == 1
    assert "Invalid isoformat string" in capsys.readouterr().err
