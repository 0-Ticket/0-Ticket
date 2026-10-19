"""Pure, replaceable result-fusion functions for Ticket similarity search."""

import math
import statistics
from collections.abc import Callable, Sequence

from soc.store.vectors.base import VectorSearchHit

FusionFunction = Callable[..., list[tuple[str, float]]]


def _deduplicate(hits: Sequence[VectorSearchHit]) -> list[VectorSearchHit]:
    unique: dict[str, VectorSearchHit] = {}
    for hit in hits:
        unique.setdefault(hit.ticket_id, hit)
    return list(unique.values())


def _positive_weights(keyword_weight: float, vector_weight: float) -> None:
    if (
        not math.isfinite(keyword_weight)
        or not math.isfinite(vector_weight)
        or keyword_weight <= 0
        or vector_weight <= 0
    ):
        raise ValueError("fusion_weights_must_be_positive_finite_numbers")


def _finish(scores: dict[str, float], k: int) -> list[tuple[str, float]]:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("search_limit_must_be_positive")
    if any(not math.isfinite(score) for score in scores.values()):
        raise ValueError("fusion_scores_must_be_finite")
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [(ticket_id, float(score)) for ticket_id, score in ranked[:k]]


def fuse_keyword_first(
    keyword_hits: Sequence[VectorSearchHit],
    vector_hits: Sequence[VectorSearchHit],
    *,
    k: int,
    keyword_weight: float = 1.0,
    vector_weight: float = 1.0,
    rank_constant: int = 60,
) -> list[tuple[str, float]]:
    """Put exact keyword matches first, then fill with semantic-only results."""
    del keyword_weight, vector_weight, rank_constant
    keyword = sorted(_deduplicate(keyword_hits), key=lambda hit: (-hit.score, hit.ticket_id))
    keyword_ids = {hit.ticket_id for hit in keyword}
    semantic = sorted(
        (hit for hit in _deduplicate(vector_hits) if hit.ticket_id not in keyword_ids),
        key=lambda hit: (-hit.score, hit.ticket_id),
    )
    combined = [*keyword, *semantic]
    return _finish(
        {hit.ticket_id: float(len(combined) - rank) for rank, hit in enumerate(combined)}, k
    )


def fuse_rrf(
    keyword_hits: Sequence[VectorSearchHit],
    vector_hits: Sequence[VectorSearchHit],
    *,
    k: int,
    keyword_weight: float = 1.0,
    vector_weight: float = 1.0,
    rank_constant: int = 60,
) -> list[tuple[str, float]]:
    """Fuse ranked lists with equal-weight reciprocal rank contributions."""
    del keyword_weight, vector_weight
    return fuse_weighted_rrf(
        keyword_hits,
        vector_hits,
        k=k,
        keyword_weight=1.0,
        vector_weight=1.0,
        rank_constant=rank_constant,
    )


def fuse_weighted_rrf(
    keyword_hits: Sequence[VectorSearchHit],
    vector_hits: Sequence[VectorSearchHit],
    *,
    k: int,
    keyword_weight: float = 1.0,
    vector_weight: float = 1.0,
    rank_constant: int = 60,
) -> list[tuple[str, float]]:
    """Fuse ranked lists while allowing either retrieval leg to receive more weight."""
    _positive_weights(keyword_weight, vector_weight)
    if isinstance(rank_constant, bool) or not isinstance(rank_constant, int) or rank_constant < 1:
        raise ValueError("rrf_rank_constant_must_be_positive")
    scores: dict[str, float] = {}
    for weight, hits in (
        (keyword_weight, _deduplicate(keyword_hits)),
        (vector_weight, _deduplicate(vector_hits)),
    ):
        for rank, hit in enumerate(hits):
            scores[hit.ticket_id] = scores.get(hit.ticket_id, 0.0) + weight / (rank_constant + rank)
    return _finish(scores, k)


def _distribution_scores(hits: Sequence[VectorSearchHit]) -> dict[str, float]:
    unique = _deduplicate(hits)
    if not unique:
        return {}
    values = [float(hit.score) for hit in unique]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("fusion_scores_must_be_finite")
    if len(values) == 1:
        return {unique[0].ticket_id: 0.5}
    deviation = statistics.stdev(values)
    if deviation == 0:
        return {hit.ticket_id: 0.5 for hit in unique}
    mean = statistics.fmean(values)
    lower = mean - 3 * deviation
    scale = 6 * deviation
    return {hit.ticket_id: (float(hit.score) - lower) / scale for hit in unique}


def fuse_dbsf(
    keyword_hits: Sequence[VectorSearchHit],
    vector_hits: Sequence[VectorSearchHit],
    *,
    k: int,
    keyword_weight: float = 1.0,
    vector_weight: float = 1.0,
    rank_constant: int = 60,
) -> list[tuple[str, float]]:
    """Fuse score lists after per-query distribution normalization (DBSF)."""
    del rank_constant
    _positive_weights(keyword_weight, vector_weight)
    scores: dict[str, float] = {}
    for weight, hits in (
        (keyword_weight, keyword_hits),
        (vector_weight, vector_hits),
    ):
        for ticket_id, score in _distribution_scores(hits).items():
            scores[ticket_id] = scores.get(ticket_id, 0.0) + weight * score
    return _finish(scores, k)


def _min_max_scores(hits: Sequence[VectorSearchHit]) -> dict[str, float]:
    unique = _deduplicate(hits)
    if not unique:
        return {}
    values = [float(hit.score) for hit in unique]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("fusion_scores_must_be_finite")
    low = min(values)
    high = max(values)
    if low == high:
        return {hit.ticket_id: 0.5 for hit in unique}
    return {hit.ticket_id: (float(hit.score) - low) / (high - low) for hit in unique}


def fuse_weighted_score(
    keyword_hits: Sequence[VectorSearchHit],
    vector_hits: Sequence[VectorSearchHit],
    *,
    k: int,
    keyword_weight: float = 1.0,
    vector_weight: float = 1.0,
    rank_constant: int = 60,
) -> list[tuple[str, float]]:
    """Fuse per-query min-max normalized score lists with explicit weights."""
    del rank_constant
    _positive_weights(keyword_weight, vector_weight)
    scores: dict[str, float] = {}
    for weight, hits in (
        (keyword_weight, keyword_hits),
        (vector_weight, vector_hits),
    ):
        for ticket_id, score in _min_max_scores(hits).items():
            scores[ticket_id] = scores.get(ticket_id, 0.0) + weight * score
    return _finish(scores, k)


FUSION_FUNCTIONS: dict[str, FusionFunction] = {
    "keyword_first": fuse_keyword_first,
    "rrf": fuse_rrf,
    "weighted_rrf": fuse_weighted_rrf,
    "dbsf": fuse_dbsf,
    "weighted_score": fuse_weighted_score,
}


def fuse_search_results(
    method: str,
    keyword_hits: Sequence[VectorSearchHit],
    vector_hits: Sequence[VectorSearchHit],
    *,
    k: int,
    keyword_weight: float = 1.0,
    vector_weight: float = 1.0,
    rank_constant: int = 60,
) -> list[tuple[str, float]]:
    """Run a named built-in fusion function; each method is independently replaceable."""
    try:
        fusion = FUSION_FUNCTIONS[method]
    except KeyError:
        raise ValueError("unknown_vector_fusion_method") from None
    return fusion(
        keyword_hits,
        vector_hits,
        k=k,
        keyword_weight=keyword_weight,
        vector_weight=vector_weight,
        rank_constant=rank_constant,
    )
