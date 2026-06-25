from __future__ import annotations

from app.scoring import PlaceholderScorer, placeholder_probability, rank_candidates
from tests.fixtures import candidate


def test_placeholder_scorer_is_stable_and_bounded() -> None:
    scorer = PlaceholderScorer()
    candidates = [candidate(index=1), candidate(index=2)]

    first = scorer.score(candidates)
    second = scorer.score(candidates)

    assert [item.predicted_probability for item in first] == [
        item.predicted_probability for item in second
    ]
    assert all(0 <= item.predicted_probability <= 1 for item in first)


def test_higher_line_receives_penalty_for_same_key_parts() -> None:
    low_line = candidate(index=1, line=0.5)
    high_line = candidate(index=1, line=1.5)

    assert placeholder_probability(high_line) <= 0.99
    assert placeholder_probability(high_line) < (
        0.50
        + 0.24
        * (
            int.from_bytes(
                __import__("hashlib")
                .sha256("evt-1|Player 1|1.5".encode("utf-8"))
                .digest()[:4],
                "big",
            )
            / 2**32
        )
    )
    assert placeholder_probability(low_line) != placeholder_probability(
        high_line
    )


def test_ranking_tie_breaking_is_deterministic() -> None:
    scored = PlaceholderScorer().score(
        [candidate(index=3), candidate(index=2), candidate(index=1)]
    )

    first = rank_candidates(scored)
    second = rank_candidates(scored)

    assert [item.candidate.player_name for item in first] == [
        item.candidate.player_name for item in second
    ]
    assert [item.rank for item in first] == [1, 2, 3]
