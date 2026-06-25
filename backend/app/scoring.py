from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from typing import Protocol

from app.domain import PropCandidate, ScoredCandidate


class CandidateScorer(Protocol):
    model_version: str
    feature_version: str

    def score(
        self,
        candidates: Sequence[PropCandidate],
    ) -> list[ScoredCandidate]:
        ...


class PlaceholderScorer:
    """Deterministic test scorer; these are not trained model outputs."""

    model_version = "placeholder-v0"
    feature_version = "none-v0"

    def score(
        self,
        candidates: Sequence[PropCandidate],
    ) -> list[ScoredCandidate]:
        return [
            ScoredCandidate(
                candidate=candidate,
                predicted_probability=placeholder_probability(candidate),
            )
            for candidate in candidates
        ]


def placeholder_probability(candidate: PropCandidate) -> float:
    key = (
        f"{candidate.provider_event_id}|"
        f"{candidate.player_name}|"
        f"{candidate.line}"
    )
    digest = sha256(key.encode("utf-8")).digest()
    unit_value = int.from_bytes(digest[:4], "big") / 2**32
    probability = 0.50 + 0.24 * unit_value
    probability -= 0.05 * max(candidate.line - 0.5, 0.0)
    return min(max(probability, 0.01), 0.99)


def rank_candidates(
    scored_candidates: Sequence[ScoredCandidate],
) -> list[ScoredCandidate]:
    sorted_candidates = sorted(
        scored_candidates,
        key=lambda scored: (
            -scored.predicted_probability,
            scored.candidate.commence_time,
            scored.candidate.player_name,
            scored.candidate.line,
        ),
    )
    return [
        ScoredCandidate(
            candidate=scored.candidate,
            predicted_probability=scored.predicted_probability,
            rank=index,
            eligible=scored.eligible,
            exclusion_reason=scored.exclusion_reason,
        )
        for index, scored in enumerate(sorted_candidates, start=1)
    ]
